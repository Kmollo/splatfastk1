"""Replicate client for SplatfastK1.

Two layers:
  * test_connection — used by Settings page to validate the user's API key.
  * Prediction lifecycle (get_latest_version, upload_file, submit_prediction,
    poll_prediction, download_output) — used by CloudPipelineWorker to run
    Brush on Replicate.

All calls use urllib so we have no extra runtime deps.
"""
from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


REPLICATE_API_BASE = "https://api.replicate.com/v1"
DEFAULT_MODEL = "kmollo/splatfastk1-brush"

# Optional supply-chain hardening: if PINNED_VERSION_ID is set, we'll use it
# verbatim instead of asking Replicate for "the latest". This means a
# compromise of the Replicate model (e.g. someone publishing a malicious new
# version) doesn't auto-affect users. To pin, replace the empty string with a
# version id you've personally vetted (the 64-char hex string under "Versions"
# on the Replicate model page). Empty string = always fetch latest.
PINNED_VERSION_ID = ""

# Hosts we're willing to download prediction outputs from. Locked down to
# prevent SSRF (e.g. a compromised Replicate response trying to point us at
# 169.254.169.254/metadata or some local service). Replicate routes all
# prediction outputs through *.replicate.delivery; api.replicate.com is for
# files uploaded via the Files API.
_TRUSTED_OUTPUT_HOSTS = ("replicate.delivery", "api.replicate.com")


def _host_is_trusted(url: str) -> bool:
    """Return True if url is HTTPS on one of our allowed hosts."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host == h or host.endswith("." + h) for h in _TRUSTED_OUTPUT_HOSTS)


class ReplicateError(Exception):
    """Raised on any Replicate API error or unexpected response."""


@dataclass(frozen=True)
class AccountInfo:
    username: str
    name: str
    type: str  # "user" or "organization"


# ---------------------------------------------------------------------------
# Low-level HTTP helper
# ---------------------------------------------------------------------------

def _request(
    method: str,
    path: str,
    api_key: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict[str, str], bytes]:
    """Make a Replicate API request. Returns (status, headers, body_bytes)."""
    url = path if path.startswith("http") else f"{REPLICATE_API_BASE}{path}"
    h = {
        "Authorization": f"Bearer {api_key.strip()}",
        "User-Agent": "SplatfastK1/0.1",
    }
    if headers:
        h.update(headers)

    req = urllib.request.Request(url, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        body_bytes = b""
        try:
            body_bytes = e.read()
        except Exception:
            pass
        return e.code, dict(e.headers or {}), body_bytes
    except urllib.error.URLError as e:
        raise ReplicateError(f"Network error: {e.reason}") from e
    except TimeoutError as e:
        raise ReplicateError("Request to Replicate timed out") from e


def _parse_json(body_bytes: bytes) -> dict[str, Any]:
    if not body_bytes:
        return {}
    try:
        return json.loads(body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ReplicateError("Replicate returned unexpected non-JSON response") from e


def _raise_for_status(status: int, body_bytes: bytes, context: str) -> None:
    if 200 <= status < 300:
        return
    detail = ""
    try:
        data = _parse_json(body_bytes)
        detail = data.get("detail") or data.get("title") or ""
    except ReplicateError:
        detail = body_bytes.decode("utf-8", errors="replace")[:200]
    if status == 401:
        raise ReplicateError(
            "Replicate rejected your API key. Re-paste your token in Settings."
        )
    if status == 402:
        raise ReplicateError(
            "You're out of Replicate credits. Add a payment method or top up at "
            "replicate.com/account/billing — splat trainings cost about $0.10 each."
        )
    if status == 403:
        raise ReplicateError(
            "Replicate denied access. You may need billing set up at "
            "replicate.com/account/billing."
        )
    if status == 404:
        raise ReplicateError(f"Not found. {context}")
    if status == 429:
        raise ReplicateError(
            "Replicate is rate-limiting requests. Try again in a moment."
        )
    raise ReplicateError(f"Replicate returned HTTP {status}. {context} {detail}".strip())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def test_connection(api_key: str, timeout: float = 10.0) -> AccountInfo:
    """Validate an API key by calling /v1/account. Returns AccountInfo on success."""
    if not api_key or not api_key.strip():
        raise ReplicateError("No API key provided.")
    status, _, body = _request("GET", "/account", api_key, timeout=timeout)
    _raise_for_status(status, body, "Could not verify account.")
    data = _parse_json(body)
    username = data.get("username") or ""
    if not username:
        raise ReplicateError("Replicate response missing a username field.")
    return AccountInfo(
        username=username,
        name=data.get("name") or username,
        type=data.get("type") or "user",
    )


def get_latest_version_id(api_key: str, model: str = DEFAULT_MODEL) -> str:
    """Return the version id to use for predictions.

    If PINNED_VERSION_ID is set (supply-chain hardening), return that without
    contacting Replicate. Otherwise look up the latest published version.
    """
    if PINNED_VERSION_ID:
        return PINNED_VERSION_ID
    status, _, body = _request("GET", f"/models/{model}", api_key, timeout=15)
    _raise_for_status(status, body, f"Could not look up model {model}.")
    data = _parse_json(body)
    version = (data.get("latest_version") or {}).get("id")
    if not version:
        raise ReplicateError(
            f"Model {model} exists but has no published version yet. "
            "The publish workflow may not have finished."
        )
    return version


def upload_file(api_key: str, path: Path, timeout: float = 600.0) -> str:
    """Upload a local file to Replicate Files API. Returns the file URL."""
    if not path.exists():
        raise ReplicateError(f"File not found: {path}")
    filename = path.name
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    boundary = f"----SplatfastK1Boundary{int(time.time()*1000):x}"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="content"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    file_bytes = path.read_bytes()
    body = head + file_bytes + tail

    status, _, resp_body = _request(
        "POST",
        "/files",
        api_key,
        body=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        timeout=timeout,
    )
    _raise_for_status(status, resp_body, "File upload failed.")
    data = _parse_json(resp_body)
    url = ((data or {}).get("urls") or {}).get("get") or data.get("url")
    if not url:
        raise ReplicateError("Replicate upload response missing file URL.")
    return url


def submit_prediction(
    api_key: str,
    version_id: str,
    inputs: dict[str, Any],
    timeout: float = 30.0,
) -> dict[str, Any]:
    """POST /predictions and return the full prediction record."""
    body = json.dumps({"version": version_id, "input": inputs}).encode("utf-8")
    status, _, resp_body = _request(
        "POST",
        "/predictions",
        api_key,
        body=body,
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )
    _raise_for_status(status, resp_body, "Could not submit prediction.")
    return _parse_json(resp_body)


def get_prediction(api_key: str, prediction_id: str, timeout: float = 15.0) -> dict[str, Any]:
    """Fetch a prediction's current status."""
    status, _, body = _request("GET", f"/predictions/{prediction_id}", api_key, timeout=timeout)
    _raise_for_status(status, body, f"Could not read prediction {prediction_id}.")
    return _parse_json(body)


def cancel_prediction(api_key: str, prediction_id: str, timeout: float = 15.0) -> None:
    """Tell Replicate to stop a running prediction so you stop being billed.

    Without this, hitting Cancel in the app only stops US from polling — the
    GPU on Replicate's side keeps running and keeps charging your account
    until it hits the model's natural completion.

    Silently ignores 404 / 409 (already-finished predictions can't be cancelled).
    """
    status, _, body = _request(
        "POST", f"/predictions/{prediction_id}/cancel", api_key, timeout=timeout,
    )
    # 2xx = success, 404 = already gone, 409 = already finished. All fine.
    if status >= 200 and status < 300:
        return
    if status in (404, 409):
        return
    _raise_for_status(status, body, f"Could not cancel prediction {prediction_id}.")


def poll_prediction(
    api_key: str,
    prediction_id: str,
    on_status: Optional[Callable[[str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    cancel: Optional[Callable[[], bool]] = None,
    interval: float = 4.0,
    timeout: float = 60 * 30,
) -> dict[str, Any]:
    """Poll a prediction until it reaches a terminal state. Returns the final record.

    Calls on_status whenever the high-level status changes.
    Calls on_log with each NEW line of logs as they stream in.

    Raises ReplicateError on failure / cancellation / timeout.
    """
    deadline = time.time() + timeout
    last_status = ""
    seen_log_chars = 0
    while time.time() < deadline:
        if cancel and cancel():
            raise ReplicateError("Cancelled by user.")
        record = get_prediction(api_key, prediction_id)
        status = record.get("status", "")
        if status != last_status and on_status:
            on_status(status)
            last_status = status
        # Stream NEW log lines (Replicate appends to record["logs"] over time)
        if on_log:
            full_logs = record.get("logs") or ""
            if len(full_logs) > seen_log_chars:
                new_text = full_logs[seen_log_chars:]
                seen_log_chars = len(full_logs)
                for line in new_text.splitlines():
                    if line.strip():
                        on_log(line.rstrip())
        if status == "succeeded":
            return record
        if status in ("failed", "canceled"):
            err = record.get("error") or status
            raise ReplicateError(f"Prediction {status}: {err}")
        time.sleep(interval)
    raise ReplicateError("Polling timed out after 30 min.")


def download_output(url: str, dest: Path, timeout: float = 600.0) -> Path:
    """Download a prediction output URL to a local file.

    Refuses to download from any host outside our trusted allowlist
    (replicate.delivery / api.replicate.com). Belt-and-suspenders defense
    against SSRF: even if Replicate's API were compromised and returned a
    malicious output URL, we wouldn't fetch from it.
    """
    if not _host_is_trusted(url):
        raise ReplicateError(
            f"Refusing to download from untrusted host: {url!r}. "
            "Expected an https URL on replicate.delivery."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "SplatfastK1/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as out:
            while chunk := resp.read(1024 * 1024):
                out.write(chunk)
    except urllib.error.URLError as e:
        raise ReplicateError(f"Could not download output: {e.reason}") from e
    return dest
