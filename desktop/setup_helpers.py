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
            zf.extractall(BRUSH_BINARY.parent)
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

    Note: BlendSplat is a Blender asset library distributed via a community
    GitHub mirror. If the download URL is unreachable, fall back to opening
    the manual install instructions in the user's browser.
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
            zf.extractall(BLENDSPLAT_DIR)
        tmp_zip.unlink(missing_ok=True)
        if BLENDSPLAT_CORE.exists():
            return True, "BlendSplat installed"
        return False, "BlendSplat extracted but core/ folder not found"
    except Exception as e:
        return False, f"BlendSplat download failed: {e}. Install manually from BlendSplat repo."


def install_colmap(progress_cb: ProgressCb) -> Tuple[bool, str]:
    """Install COLMAP via winget. Falls back to opening the download page."""
    if check_colmap()[0] == STATUS_OK:
        return True, "COLMAP already installed"
    progress_cb(0, "Installing COLMAP via winget...")
    try:
        # Try winget first. -e for exact match, --accept-package-agreements
        # for unattended install.
        result = subprocess.run(
            ["winget", "install", "-e", "--id", "Colmap.Colmap",
             "--accept-package-agreements", "--accept-source-agreements"],
            capture_output=True, text=True, timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0 or "already installed" in (result.stdout + result.stderr).lower():
            progress_cb(100, "COLMAP installed")
            return True, "COLMAP installed via winget"
        return False, f"winget failed: {result.stderr[:200]}"
    except FileNotFoundError:
        return False, "winget not available. Install COLMAP manually from colmap.github.io"
    except Exception as e:
        return False, f"COLMAP install failed: {e}"


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
