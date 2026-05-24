"""SplatfastK1 — local configuration storage.

Secrets (Replicate API key) are stored in **Windows Credential Manager** via
the `keyring` library — the same vault Windows, Edge, and Chrome use. Never
written to disk in plaintext, never exposed to other user accounts.

Non-secret preferences (last opened project, output path overrides) live in
``%APPDATA%\\SplatfastK1\\config.json`` as plain JSON.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import keyring

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

APP_NAME = "SplatfastK1"
KEYRING_SERVICE = "SplatfastK1"
KEYRING_USER_REPLICATE = "replicate_api_token"


def app_config_dir() -> Path:
    """`%APPDATA%\\SplatfastK1\\` — created on first call."""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def app_config_file() -> Path:
    return app_config_dir() / "config.json"


def default_outputs_dir() -> Path:
    """`%USERPROFILE%\\SplatfastK1\\outputs\\` — created on first call."""
    path = Path.home() / APP_NAME / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Secret storage (Replicate API key)
# ---------------------------------------------------------------------------

def get_replicate_token() -> str | None:
    """Return the saved Replicate API token, or None if none saved."""
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER_REPLICATE)
    except Exception:
        return None


def set_replicate_token(token: str) -> None:
    """Save the Replicate API token securely in Windows Credential Manager."""
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER_REPLICATE, token)


def clear_replicate_token() -> None:
    """Remove the saved Replicate API token. No-op if none saved."""
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER_REPLICATE)
    except keyring.errors.PasswordDeleteError:
        pass


def has_replicate_token() -> bool:
    return bool(get_replicate_token())


# ---------------------------------------------------------------------------
# Non-secret preferences (plain JSON)
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    "outputs_dir": "",       # empty = use default_outputs_dir()
    "last_project_id": "",
    "default_quality": "fast",
}


def load_prefs() -> dict[str, Any]:
    """Load prefs from %APPDATA%\\SplatfastK1\\config.json. Fills in defaults."""
    cfg_file = app_config_file()
    if cfg_file.exists():
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}
    out = dict(_DEFAULTS)
    out.update({k: v for k, v in data.items() if k in _DEFAULTS})
    return out


def save_prefs(prefs: dict[str, Any]) -> None:
    """Persist prefs to %APPDATA%\\SplatfastK1\\config.json.

    Writes atomically: if the process crashes mid-write, the old config.json
    is preserved. We write to a sibling .tmp file then os.replace() it onto
    the real file (atomic rename on the same filesystem).
    """
    # Only save known keys, never accidentally write secrets
    safe = {k: v for k, v in prefs.items() if k in _DEFAULTS}
    target = app_config_file()
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(safe, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, target)


def get_pref(key: str, default: Any = None) -> Any:
    return load_prefs().get(key, default)


def set_pref(key: str, value: Any) -> None:
    prefs = load_prefs()
    prefs[key] = value
    save_prefs(prefs)


def get_outputs_dir() -> Path:
    """Resolved outputs dir — pref override if set, otherwise default."""
    override = (load_prefs().get("outputs_dir") or "").strip()
    if override:
        path = Path(override)
        path.mkdir(parents=True, exist_ok=True)
        return path
    return default_outputs_dir()
