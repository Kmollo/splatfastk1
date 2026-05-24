"""Resume a cloud splat training — rebuild zip, re-upload, submit, poll, download.

Uses the local COLMAP results that already exist on disk in the user's outputs
folder. Saves us re-running the ~2-min local prep.
"""
from __future__ import annotations

import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop import config
from desktop.cloud import (
    DEFAULT_MODEL,
    ReplicateError,
    download_output,
    get_latest_version_id,
    poll_prediction,
    submit_prediction,
    upload_file,
)


# Where the local prep produced its output
PROJECT_DIR = Path.home() / "SplatfastK1" / "outputs" / "4340824-hd_1920_1080_30fps"
OUTPUT_PLY = PROJECT_DIR / "splat" / "scene.ply"
TOTAL_STEPS = 15000  # Balanced quality


def build_zip(project_dir: Path) -> Path:
    """Bundle images/ + sparse/ into a Linux-friendly zip (forward slashes)."""
    images_dir = project_dir / "images"
    # The COLMAP output lives at reconstruction/sparse. The top-level sparse/
    # folder is empty unless a backend ran (Brush copies into it). Pick the
    # one that actually has .bin files.
    recon_sparse = project_dir / "reconstruction" / "sparse"
    top_sparse = project_dir / "sparse"
    if recon_sparse.exists() and any(recon_sparse.rglob("*.bin")):
        sparse_dir = recon_sparse
    elif top_sparse.exists() and any(top_sparse.rglob("*.bin")):
        sparse_dir = top_sparse
    else:
        raise SystemExit(f"No populated sparse dir at {recon_sparse} or {top_sparse}")
    if not images_dir.exists():
        raise SystemExit(f"Missing images dir: {images_dir}")

    zip_path = Path(tempfile.gettempdir()) / f"splatfastk1_dataset_{int(time.time())}.zip"
    n_images = 0
    n_sparse = 0
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as zf:
        for file in sorted(images_dir.rglob("*")):
            if file.is_file():
                zf.write(file, arcname=f"images/{file.relative_to(images_dir).as_posix()}")
                n_images += 1
        for file in sorted(sparse_dir.rglob("*")):
            if file.is_file():
                zf.write(file, arcname=f"sparse/{file.relative_to(sparse_dir).as_posix()}")
                n_sparse += 1
    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"Built zip: {zip_path.name} ({size_mb:.1f} MB) — {n_images} images + {n_sparse} sparse files")
    # Sanity check: list a few names so we can confirm forward slashes
    with zipfile.ZipFile(zip_path) as zf:
        sample = zf.namelist()[:5]
        print(f"  Sample entries: {sample}")
    return zip_path


def main() -> int:
    token = config.get_replicate_token() or ""
    if not token:
        print("No API key saved. Open the app's Settings page first.")
        return 1

    zip_path = build_zip(PROJECT_DIR)

    print(f"Looking up latest version of {DEFAULT_MODEL}...")
    version_id = get_latest_version_id(token, DEFAULT_MODEL)
    print(f"Version: {version_id}")

    print(f"Uploading {zip_path.stat().st_size // 1024} KB to Replicate...")
    try:
        upload_url = upload_file(token, zip_path)
    except ReplicateError as e:
        print(f"FAILED at upload: {e}")
        return 1
    print(f"Upload URL: {upload_url}")

    print(f"Submitting prediction (steps={TOTAL_STEPS})...")
    try:
        prediction = submit_prediction(
            token,
            version_id,
            {"colmap_zip": upload_url, "total_steps": TOTAL_STEPS},
        )
    except ReplicateError as e:
        print(f"FAILED at submit: {e}")
        return 1
    pred_id = prediction["id"]
    print(f"Prediction ID: {pred_id}")
    print("Polling...")

    started = time.time()
    def on_status(s: str) -> None:
        secs = int(time.time() - started)
        print(f"  [{secs:3d}s] status: {s}")

    try:
        final = poll_prediction(token, pred_id, on_status=on_status)
    except ReplicateError as e:
        print(f"FAILED while polling: {e}")
        return 1

    output = final.get("output")
    output_url = output[0] if isinstance(output, list) else str(output or "")
    if not output_url:
        print("Prediction succeeded but no output URL.")
        return 1

    print(f"Downloading {output_url} -> {OUTPUT_PLY}")
    download_output(output_url, OUTPUT_PLY)
    size_mb = OUTPUT_PLY.stat().st_size / 1024 / 1024
    print(f"DONE. scene.ply = {size_mb:.1f} MB at {OUTPUT_PLY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
