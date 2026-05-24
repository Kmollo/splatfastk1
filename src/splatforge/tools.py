from __future__ import annotations

import shutil
from pathlib import Path


TOOL_ALIASES = {
    "ffmpeg": ["ffmpeg", "ffmpeg.exe"],
    "colmap": ["colmap", "colmap.exe", "COLMAP.bat"],
    "glomap": ["glomap", "glomap.exe"],
    "brush": ["brush", "brush.exe", "brush_app", "brush_app.exe", "brush_app_windows.exe"],
    "blender": ["blender", "blender.exe"],
}


LOCAL_TOOL_DIRS = [
    Path("tools"),
    Path("tools") / "bin",
    Path("tools") / "colmap",
    Path("tools") / "colmap" / "bin",
    Path("tools") / "glomap",
    Path("tools") / "glomap" / "bin",
    Path("tools") / "brush",
    Path("references") / "skysplat_blender" / "binaries",
]


def resolve_tool(name: str, root: Path | None = None) -> str | None:
    aliases = TOOL_ALIASES.get(name, [name])
    for alias in aliases:
        path = shutil.which(alias)
        if path:
            return path

    root = (root or Path.cwd()).resolve()
    for directory in LOCAL_TOOL_DIRS:
        base = root / directory
        for alias in aliases:
            candidate = base / alias
            if candidate.exists() and candidate.is_file():
                return str(candidate.resolve())

    for candidate in iter_windows_package_candidates(aliases):
        return str(candidate.resolve())
    return None


def command_for_tool(name: str, root: Path | None = None) -> str:
    return resolve_tool(name, root) or name


def iter_windows_package_candidates(aliases: list[str]):
    package_root = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if not package_root.exists():
        return
    normalized = {alias.lower() for alias in aliases}
    for path in package_root.rglob("*"):
        if path.is_file() and path.name.lower() in normalized:
            yield path
