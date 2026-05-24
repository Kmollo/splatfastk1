from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass

from .hardware import collect_hardware
from .tools import resolve_tool


@dataclass(frozen=True)
class ToolStatus:
    name: str
    command: str
    found: bool
    path: str | None
    version: str | None
    required: bool
    hint: str


TOOLS = [
    (
        "ffmpeg",
        "ffmpeg",
        True,
        "Windows: winget install Gyan.FFmpeg. macOS: brew install ffmpeg.",
    ),
    (
        "colmap",
        "colmap",
        True,
        "Install COLMAP from https://github.com/colmap/colmap/releases or your package manager.",
    ),
    (
        "glomap",
        "glomap",
        False,
        "Optional. Install GLOMAP for global SfM, or use COLMAP mapper fallback.",
    ),
    (
        "brush",
        "brush",
        True,
        "Install Brush from https://github.com/ArthurBrussee/brush/releases or build it with Cargo.",
    ),
    (
        "blender",
        "blender",
        False,
        "Install Blender from https://www.blender.org/download/ and add it to PATH if desired.",
    ),
]


def get_tool_status(name: str, command: str, required: bool, hint: str) -> ToolStatus:
    path = resolve_tool(name)
    version = None

    if path:
        try:
            result = subprocess.run(
                [path, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                # Hide the console window flash under pythonw.exe (Windows-only;
                # getattr returns 0 elsewhere, which is a no-op for subprocess).
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            version = (result.stdout or result.stderr).splitlines()[0].strip() or None
        except Exception as exc:  # pragma: no cover - defensive around third-party binaries
            version = f"version check failed: {exc}"

    return ToolStatus(
        name=name,
        command=command,
        found=path is not None,
        path=path,
        version=version,
        required=required,
        hint=hint,
    )


def collect_diagnostics() -> list[ToolStatus]:
    return [
        get_tool_status(name, command, required, hint)
        for name, command, required, hint in TOOLS
    ]


def run_doctor(as_json: bool = False, include_hardware: bool = False) -> int:
    statuses = collect_diagnostics()
    hardware = collect_hardware() if include_hardware else None

    if as_json:
        payload: object = [asdict(status) for status in statuses]
        if include_hardware:
            payload = {
                "tools": [asdict(status) for status in statuses],
                "hardware": hardware.to_dict() if hardware else None,
            }
        print(json.dumps(payload, indent=2))
    else:
        print("SplatfastK1 dependency check")
        print()
        for status in statuses:
            mark = "OK" if status.found else "MISSING"
            requirement = "required" if status.required else "optional"
            print(f"[{mark}] {status.name} ({requirement})")
            if status.path:
                print(f"  path: {status.path}")
            if status.version:
                print(f"  version: {status.version}")
            if not status.found:
                print(f"  fix: {status.hint}")
        print()
        print("Install missing required tools before running a full reconstruction.")
        if hardware:
            print()
            print("Hardware")
            print(f"  OS: {hardware.os}")
            if hardware.cpu:
                print(f"  CPU: {hardware.cpu}")
            if hardware.physical_cores or hardware.logical_cores:
                print(
                    "  Cores: "
                    f"{hardware.physical_cores or '?'} physical / "
                    f"{hardware.logical_cores or '?'} logical"
                )
            if hardware.ram_gb is not None:
                print(f"  RAM: {hardware.ram_gb} GB")
            if hardware.gpu:
                print(f"  GPU: {hardware.gpu}")
            if hardware.vram_gb is not None:
                print(f"  VRAM: {hardware.vram_gb} GB")
            print(f"  Free disk: {hardware.free_disk_gb} GB")
            print(f"  Tier: {hardware.tier}")
            print(f"  Recommendation: {hardware.recommendation}")

    missing_required = [status.name for status in statuses if status.required and not status.found]
    return 1 if missing_required else 0
