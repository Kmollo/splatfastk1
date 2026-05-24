"""Cancel any in-progress Replicate predictions to stop further GPU billing."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop import config


def main() -> int:
    token = config.get_replicate_token() or ""
    if not token:
        print("No API key saved.")
        return 1

    # List recent predictions
    req = urllib.request.Request(
        "https://api.replicate.com/v1/predictions?limit=10",
        headers={"Authorization": f"Bearer {token}", "User-Agent": "SplatfastK1/0.1"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    in_flight = [p for p in data.get("results", []) if p.get("status") in ("starting", "processing")]
    if not in_flight:
        print("No in-flight predictions. Nothing to cancel.")
        return 0

    for p in in_flight:
        pid = p["id"]
        print(f"Cancelling {pid} (status={p.get('status')})...", end=" ")
        cancel_req = urllib.request.Request(
            f"https://api.replicate.com/v1/predictions/{pid}/cancel",
            method="POST",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "SplatfastK1/0.1"},
        )
        try:
            with urllib.request.urlopen(cancel_req, timeout=15) as r:
                print(f"OK ({r.status})")
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
