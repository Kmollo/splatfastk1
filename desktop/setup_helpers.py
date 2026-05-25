"""Dependency detection + auto-install helpers for the Setup view.

Two layers:
  * check_*() functions  — return (status, detail_string). Fast disk reads only,
                           no network calls. Called every app launch.
  * install_*() functions — slow, network-bound. Each takes a progress callback
                            (pct, message) and returns (success, detail_string).

Required deps (without these, training cannot work):
  - Brush binary
  - BlendSplat library
  - COLMAP

Optional deps (training still works without these, but Open-in-Blender or cloud
training will be unavailable):
  - Blender 5.1
  - Replicate API key
"""
from __future__ import annotations

import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional, Tuple


SPLATFORGE_ROOT = Path(__file__).resolve().parents[1]


# Where things live on disk (matches the rest of the codebase)
BRUSH_BINARY = SPLATFORGE_ROOT / "references" / "skysplat_blender" / "binaries" / "brush_app_windows.exe"
BLENDSPLAT_DIR = Path(os.environ.get("USERPROFILE", "")) / "Documents" / "BlendSplat-Library"
BLENDSPLAT_CORE = BLENDSPLAT_DIR / "core"

# Download URLs — pinned versions for reproducibility
BRUSH_RELEASE_URL = (
    "https://github.com/ArthurBrussee/brush/releases/download/v0.3.0/"
    "brush-app-x86_64-pc-windows-msvc.zip"
)
# BlendSplat — community Blender asset library hosted on Codeberg.
# The source repo uses Git LFS for the .blend files, so the git-archive zip
# only contains LFS pointer stubs — we have to use the proper "release"
# asset URL which packages the real binaries. Pinned to v0.5.1; if you want
# the latest, replace with .../releases/latest/... but verify first.
BLENDSPLAT_DOWNLOAD_URL = (
    "https://codeberg.org/soerensc/BlendSplat-Library/releases/download/v0.5.1/"
    "blendsplat-core-v0.5.1.zip"
)

# COLMAP — official 4.0.4 Windows build (no-CUDA, 111 MB).
# We use no-CUDA so it works on every machine without needing the CUDA
# runtime installed separately. COLMAP runs all three steps we need
# (feature_extractor, sequential_matcher, mapper) without CUDA — just
# slower for feature matching on huge image sets. For our 22-90 frame
# workflows that doesn't matter.
#
# Verified: commit 5b76f53 from this release is byte-identical to the
# locally-bundled COLMAP that has been tested with our pipeline. The
# version string reads "4.1.0.dev0" because they tagged 4.0.4 from a
# main-branch commit that was already labeled as "next-version dev".
COLMAP_DOWNLOAD_URL = (
    "https://github.com/colmap/colmap/releases/download/4.0.4/"
    "colmap-x64-windows-nocuda.zip"
)
COLMAP_LOCAL_DIR = SPLATFORGE_ROOT / "tools" / "colmap"
COLMAP_LOCAL_BAT = COLMAP_LOCAL_DIR / "COLMAP.bat"


# ---------------------------------------------------------------------------
# Status enum (using strings — keeps it simple, easy to display)
# ---------------------------------------------------------------------------

STATUS_OK = "ok"           # green check
STATUS_MISSING = "missing" # red X — auto-installable
STATUS_MANUAL = "manual"   # yellow — user must do something


# ---------------------------------------------------------------------------
# Detectors — fast, no network. Return (status, friendly_detail)
# ---------------------------------------------------------------------------

def check_python() -> Tuple[str, str]:
    """Python is obviously installed since this module is running."""
    import sys
    v = sys.version_info
    return STATUS_OK, f"Python {v.major}.{v.minor}.{v.micro}"


def check_ffmpeg() -> Tuple[str, str]:
    exe = shutil.which("ffmpeg")
    if exe:
        return STATUS_OK, exe
    return STATUS_MANUAL, "Not on PATH — install via winget after setup"


def check_colmap() -> Tuple[str, str]:
    # Common locations: PATH, the bundled COLMAP.bat under tools/, scoop
    exe = shutil.which("colmap")
    if exe:
        return STATUS_OK, exe
    local_bat = SPLATFORGE_ROOT / "tools" / "colmap" / "COLMAP.bat"
    if local_bat.exists():
        return STATUS_OK, str(local_bat)
    return STATUS_MISSING, "Not installed"


def check_brush() -> Tuple[str, str]:
    if BRUSH_BINARY.exists() and BRUSH_BINARY.stat().st_size > 1_000_000:
        size_mb = BRUSH_BINARY.stat().st_size / 1024 / 1024
        return STATUS_OK, f"{size_mb:.0f} MB at references/"
    return STATUS_MISSING, "Not downloaded"


def check_blendsplat() -> Tuple[str, str]:
    if BLENDSPLAT_CORE.exists() and any(BLENDSPLAT_CORE.glob("*.blend")):
        return STATUS_OK, str(BLENDSPLAT_DIR)
    return STATUS_MISSING, "Not in Documents/BlendSplat-Library"


def check_blender() -> Tuple[str, str]:
    candidates = [
        Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"),
    ]
    for p in candidates:
        if p.exists():
            return STATUS_OK, str(p.parent.name)
    exe = shutil.which("blender")
    if exe:
        return STATUS_OK, exe
    return STATUS_MANUAL, "Not installed — download from blender.org"


def check_replicate_key() -> Tuple[str, str]:
    try:
        from desktop import config
        if config.has_replicate_token():
            return STATUS_OK, "Saved in Windows Credential Manager"
    except Exception:
        pass
    return STATUS_MANUAL, "Not saved — free signup at replicate.com"


def all_required_ok() -> bool:
    """True iff every REQUIRED dependency is installed.

    'Required' means the app cannot do its core job without it. Optional
    dependencies (Blender, Replicate key) don't block the Setup view.
    """
    return (
        check_brush()[0] == STATUS_OK
        and check_blendsplat()[0] == STATUS_OK
        and check_colmap()[0] == STATUS_OK
    )


# ---------------------------------------------------------------------------
# Installers — slow, network-bound. progress_cb(pct, msg) gets called.
# ---------------------------------------------------------------------------

ProgressCb = Callable[[int, str], None]


def _download_with_progress(url: str, dest: Path, progress_cb: ProgressCb,
                            label: str) -> None:
    """Download a URL to dest, calling progress_cb(pct, msg) as bytes arrive."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "SplatfastK1/0.1"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 1024 * 256  # 256 KB
        with open(dest, "wb") as out:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = int(downloaded * 100 / total)
                    mb = downloaded / 1024 / 1024
                    total_mb = total / 1024 / 1024
                    progress_cb(pct, f"{label} — {mb:.1f} / {total_mb:.1f} MB")
                else:
                    mb = downloaded / 1024 / 1024
                    progress_cb(50, f"{label} — {mb:.1f} MB so far")


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract a zip with zip-slip protection.

    A malicious zip can contain entries like ``../../etc/passwd`` or absolute
    paths. Python's plain ``zf.extractall()`` happily writes outside ``dest``
    on those. We validate each entry's resolved path stays under ``dest`` and
    skip anything that escapes. Mirrors the guard in
    ``replicate_model/predict.py``.

    This matters even though we download from official Brush + BlendSplat
    release URLs over HTTPS: if either upstream repo is ever compromised, or
    a corporate MITM strips HTTPS, this is our second line of defense.
    """
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    for member in zf.infolist():
        name = member.filename.replace("\\", "/")
        # Block absolute paths and any traversal segment
        if name.startswith("/") or ".." in name.split("/"):
            continue
        target = (dest / name).resolve()
        try:
            target.relative_to(dest)
        except ValueError:
            continue
        zf.extract(member, str(dest))


def install_brush(progress_cb: ProgressCb) -> Tuple[bool, str]:
    """Download + extract the Brush Windows binary."""
    if BRUSH_BINARY.exists():
        return True, "Brush already installed"
    progress_cb(0, "Downloading Brush binary...")
    tmp_zip = SPLATFORGE_ROOT / "references" / "_brush_download.zip"
    try:
        _download_with_progress(BRUSH_RELEASE_URL, tmp_zip, progress_cb, "Brush")
        progress_cb(95, "Extracting Brush...")
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            _safe_extract(zf, BRUSH_BINARY.parent)
        # Brush zip may put the exe at different paths depending on release.
        # Find any .exe in the extract folder and rename to brush_app_windows.exe
        if not BRUSH_BINARY.exists():
            for p in BRUSH_BINARY.parent.rglob("*.exe"):
                if "brush" in p.name.lower():
                    p.rename(BRUSH_BINARY)
                    break
        tmp_zip.unlink(missing_ok=True)
        if BRUSH_BINARY.exists():
            return True, "Brush installed"
        return False, "Brush exe not found in downloaded zip"
    except Exception as e:
        return False, f"Brush install failed: {e}"


def install_blendsplat(progress_cb: ProgressCb) -> Tuple[bool, str]:
    """Download + extract the BlendSplat library to Documents/BlendSplat-Library/.

    Source: pinned Codeberg release. Extraction uses zip-slip-safe path
    validation so even a compromised upstream zip can't write outside the
    install directory.
    """
    if BLENDSPLAT_CORE.exists():
        return True, "BlendSplat already installed"
    progress_cb(0, "Downloading BlendSplat library...")
    BLENDSPLAT_DIR.mkdir(parents=True, exist_ok=True)
    tmp_zip = BLENDSPLAT_DIR.parent / "_blendsplat_download.zip"
    try:
        _download_with_progress(BLENDSPLAT_DOWNLOAD_URL, tmp_zip, progress_cb,
                                "BlendSplat")
        progress_cb(95, "Extracting BlendSplat...")
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            _safe_extract(zf, BLENDSPLAT_DIR)
        tmp_zip.unlink(missing_ok=True)
        if BLENDSPLAT_CORE.exists():
            return True, "BlendSplat installed"
        return False, "BlendSplat extracted but core/ folder not found"
    except Exception as e:
        return False, f"BlendSplat download failed: {e}. Install manually from BlendSplat repo."


def install_colmap(progress_cb: ProgressCb) -> Tuple[bool, str]:
    """Download + extract the official COLMAP 4.0.4 Windows build to tools/colmap/.

    Originally used `winget install Colmap.Colmap` but that package doesn't
    exist in the winget repo (we'd silently get "No package found matching
    input criteria"). The official COLMAP releases ship pre-built Windows
    zips; we just grab one of those.
    """
    if check_colmap()[0] == STATUS_OK:
        return True, "COLMAP already installed"
    progress_cb(0, "Downloading COLMAP 4.0.4 (no-CUDA, ~111 MB)...")
    COLMAP_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    tmp_zip = COLMAP_LOCAL_DIR.parent / "_colmap_download.zip"
    try:
        _download_with_progress(COLMAP_DOWNLOAD_URL, tmp_zip, progress_cb, "COLMAP")
        progress_cb(95, "Extracting COLMAP...")
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            _safe_extract(zf, COLMAP_LOCAL_DIR)
        # The COLMAP release zip has the .bat at its root. Verify it landed
        # where the pipeline expects (tools/colmap/COLMAP.bat).
        tmp_zip.unlink(missing_ok=True)
        if COLMAP_LOCAL_BAT.exists():
            return True, f"COLMAP installed at {COLMAP_LOCAL_DIR}"
        # If the zip wraps everything in a sub-folder, look one level deeper.
        for inner in COLMAP_LOCAL_DIR.iterdir():
            inner_bat = inner / "COLMAP.bat"
            if inner.is_dir() and inner_bat.exists():
                # Flatten: move everything from inner/ up into COLMAP_LOCAL_DIR
                for child in inner.iterdir():
                    shutil.move(str(child), str(COLMAP_LOCAL_DIR / child.name))
                inner.rmdir()
                if COLMAP_LOCAL_BAT.exists():
                    return True, f"COLMAP installed at {COLMAP_LOCAL_DIR}"
        return False, "COLMAP zip extracted but COLMAP.bat not found at expected path"
    except Exception as e:
        return False, f"COLMAP download failed: {e}"


# ---------------------------------------------------------------------------
# Quick summary used by both the Setup view and the Settings re-check button
# ---------------------------------------------------------------------------

def summarize_all() -> list[Tuple[str, str, str, bool]]:
    """Return (name, status, detail, required) for every dep, in display order."""
    return [
        ("Python",             *check_python(),         True),
        ("FFmpeg",             *check_ffmpeg(),         False),
        ("COLMAP",             *check_colmap(),         True),
        ("Brush binary",       *check_brush(),          True),
        ("BlendSplat library", *check_blendsplat(),     True),
        ("Blender 5.1",        *check_blender(),        False),
        ("Replicate API key",  *check_replicate_key(),  False),
    ]
