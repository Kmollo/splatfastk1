"""Quick diagnostic — list recent Replicate predictions and their status."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop import config


def main() -> int:
    token = config.get_replicate_token() or ""
    if not token:
        print("No API key saved.")
        return 1

    req = urllib.request.Request(
        "https://api.replicate.com/v1/predictions?limit=5",
        headers={"Authorization": f"Bearer {token}", "User-Agent": "SplatfastK1/0.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}")
        return 1

    print(f"Last {len(data.get('results', []))} predictions:")
    print()
    for p in data.get("results", []):
        status = p.get("status", "?")
        created = p.get("created_at", "")
        started = p.get("started_at", "")
        completed = p.get("completed_at", "")
        pid = p.get("id", "")
        model = p.get("model", "")
        version = (p.get("version") or "")[:12]
        error = p.get("error") or ""
        print(f"  {pid}")
        print(f"    model:     {model}")
        print(f"    version:   {version}...")
        print(f"    status:    {status}")
        print(f"    created:   {created}")
        if started:
            print(f"    started:   {started}")
        if completed:
            print(f"    completed: {completed}")
        if error:
            print(f"    error:     {str(error)[:120]}")
        # Pull last few lines of logs if available
        logs = p.get("logs") or ""
        if logs:
            tail = "\n".join(logs.strip().splitlines()[-3:])
            print(f"    log tail:")
            for line in tail.splitlines():
                print(f"      {line}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
