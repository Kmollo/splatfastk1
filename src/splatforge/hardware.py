from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


BYTES_PER_GB = 1024**3


@dataclass(frozen=True)
class HardwareReport:
    os: str
    cpu: str | None
    physical_cores: int | None
    logical_cores: int | None
    ram_gb: float | None
    gpu: str | None
    vram_gb: float | None
    free_disk_gb: float
    tier: str
    recommendation: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def collect_hardware(workspace: Path | None = None) -> HardwareReport:
    workspace = workspace or Path.cwd()
    disk = shutil.disk_usage(workspace)
    free_disk_gb = round(disk.free / BYTES_PER_GB, 1)

    system = platform.system()
    cpu = platform.processor() or None
    physical_cores = None
    logical_cores = None
    ram_gb = None
    gpu = None
    vram_gb = None

    if system == "Windows":
        windows = collect_windows_hardware()
        cpu = windows.get("cpu") or cpu
        physical_cores = as_int(windows.get("physical_cores"))
        logical_cores = as_int(windows.get("logical_cores"))
        ram_gb = as_float(windows.get("ram_gb"))
        gpu = windows.get("gpu")
        vram_gb = as_float(windows.get("vram_gb"))
        if ram_gb is None:
            ram_gb = collect_windows_ram_from_systeminfo()

    tier, recommendation = classify_hardware(ram_gb, vram_gb, free_disk_gb)
    return HardwareReport(
        os=f"{platform.system()} {platform.release()}",
        cpu=cpu,
        physical_cores=physical_cores,
        logical_cores=logical_cores,
        ram_gb=ram_gb,
        gpu=gpu,
        vram_gb=vram_gb,
        free_disk_gb=free_disk_gb,
        tier=tier,
        recommendation=recommendation,
    )


def collect_windows_hardware() -> dict[str, object]:
    script = """
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 Name,NumberOfCores,NumberOfLogicalProcessors
$computer = Get-CimInstance Win32_ComputerSystem | Select-Object -First 1 TotalPhysicalMemory
$os = Get-CimInstance Win32_OperatingSystem | Select-Object -First 1 TotalVisibleMemorySize
$gpu = Get-CimInstance Win32_VideoController |
  Sort-Object AdapterRAM -Descending |
  Select-Object -First 1 Name,AdapterRAM
$memoryBytes = if ($computer.TotalPhysicalMemory) {
  $computer.TotalPhysicalMemory
} elseif ($os.TotalVisibleMemorySize) {
  [double]$os.TotalVisibleMemorySize * 1KB
} else {
  $null
}
[pscustomobject]@{
  cpu = $cpu.Name
  physical_cores = $cpu.NumberOfCores
  logical_cores = $cpu.NumberOfLogicalProcessors
  ram_gb = if ($memoryBytes) { [math]::Round($memoryBytes / 1GB, 1) } else { $null }
  gpu = $gpu.Name
  vram_gb = if ($gpu.AdapterRAM) { [math]::Round($gpu.AdapterRAM / 1GB, 1) } else { $null }
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        # Hide PowerShell's console window when launched from pythonw.exe.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def collect_windows_ram_from_systeminfo() -> float | None:
    result = subprocess.run(
        ["systeminfo"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        # Hide systeminfo's console window when launched from pythonw.exe.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        return None
    match = re.search(r"Total Physical Memory:\s+([\d,]+)\s+MB", result.stdout)
    if not match:
        return None
    mb = match.group(1).replace(",", "")
    try:
        return round(int(mb) / 1024, 1)
    except ValueError:
        return None


def classify_hardware(
    ram_gb: float | None,
    vram_gb: float | None,
    free_disk_gb: float,
) -> tuple[str, str]:
    ram = ram_gb or 0
    vram = vram_gb or 0

    if free_disk_gb < 15:
        return (
            "limited",
            "Free disk space is tight. Keep dry-run on or clear space before processing video.",
        )
    if ram_gb is None and vram_gb is None:
        return (
            "unknown",
            "Hardware details are hidden. Start with fast quality and a 10-15 second test video.",
        )
    if ram >= 32 and vram >= 8:
        return (
            "comfortable",
            "Use balanced or high quality for short captures. Start with 20-40 second videos.",
        )
    if ram >= 16 and vram >= 4:
        return (
            "workable",
            "Use fast or balanced quality first. Keep test videos around 10-25 seconds.",
        )
    if ram >= 16:
        return (
            "cpu-only/small",
            "Use fast quality and very short videos. Large scenes may be slow or fail.",
        )
    return (
        "limited",
        "Use dry-run or tiny test clips only. Cloud/GPU processing will likely be better.",
    )


def as_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def as_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
