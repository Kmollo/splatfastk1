from __future__ import annotations

import json
import shutil
import struct
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, TextIO

from .backends import BrushBackend, SplatBackend
from .doctor import collect_diagnostics
from .tools import command_for_tool
from .tools import resolve_tool


VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
IMAGE_EXTENSIONS = {".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}

QUALITY_PRESETS = {
    "fast": {"fps": 1, "max_size": 1280},
    "balanced": {"fps": 2, "max_size": 1600},
    "high": {"fps": 4, "max_size": 2200},
}

MIN_REGISTERED_IMAGES = 5
MIN_POINTS3D = 50


class PipelineLogger:
    """Writes pipeline events and subprocess output to logs/pipeline.log."""

    def __init__(self, log_dir: Path):
        log_dir.mkdir(parents=True, exist_ok=True)
        self.path = log_dir / "pipeline.log"
        self.file: TextIO = open(self.path, "a", encoding="utf-8", buffering=1)
        self.stage_started_at: float | None = None
        self._write_raw("")
        self.event("PIPELINE_START")

    def _ts(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _write_raw(self, line: str) -> None:
        self.file.write(line + "\n")
        self.file.flush()

    def event(self, message: str) -> None:
        self._write_raw(f"[{self._ts()}] {message}")

    def stage_start(self, label: str, command: list[str] | None = None) -> None:
        self.stage_started_at = time.time()
        self._write_raw("")
        self._write_raw("=" * 72)
        self.event(f"STAGE_START: {label}")
        if command:
            printable = " ".join(f'"{p}"' if " " in p else p for p in command)
            self.event(f"COMMAND: {printable}")
        self._write_raw("-" * 72)

    def subprocess_line(self, line: str) -> None:
        # Subprocess lines are written without timestamp to keep tool output readable.
        self._write_raw(line.rstrip())

    def stage_end(self, label: str, returncode: int) -> None:
        elapsed = (time.time() - self.stage_started_at) if self.stage_started_at else 0.0
        self._write_raw("-" * 72)
        self.event(f"STAGE_END: {label} (exit={returncode}, elapsed={elapsed:.1f}s)")
        self.stage_started_at = None

    def close(self, status: str = "complete") -> None:
        try:
            self.event(f"PIPELINE_END: {status}")
        finally:
            self.file.close()


@contextmanager
def _pipeline_logger(layout: dict[str, Path]) -> Iterator[PipelineLogger]:
    logger = PipelineLogger(layout["logs"])
    try:
        yield logger
        logger.close("complete")
    except BaseException as exc:
        logger.event(f"ERROR: {type(exc).__name__}: {exc}")
        logger.close("failed")
        raise


@dataclass(frozen=True)
class CreateOptions:
    source: Path
    output: Path | None
    quality: str
    matcher: str
    backend: str
    dry_run: bool = False
    continue_on_missing_tools: bool = False


def create_project(options: CreateOptions) -> int:
    source = options.source.resolve()
    if not source.exists():
        print(f"Source does not exist: {source}")
        return 2

    output = (options.output or Path.cwd() / "outputs" / source.stem).resolve()
    layout = make_layout(output)

    backend = get_backend(options.backend)
    required_tools: set[str] = {"ffmpeg", "colmap"}
    if backend is not None:
        required_tools.update(backend.required_tools)
    if source.is_dir():
        required_tools.discard("ffmpeg")
    missing_tools = get_missing_required_tools(required_tools)
    if missing_tools and not options.continue_on_missing_tools and not options.dry_run:
        print("Missing required tools: " + ", ".join(missing_tools))
        print("Run `splatforge doctor` for installation details.")
        print("Use `--continue-on-missing-tools` to create the project folder anyway.")
        return 1

    create_directories(layout)
    remove_stale_metadata(layout)

    with _pipeline_logger(layout) as logger:
        logger.event(f"source={source}")
        logger.event(f"output={output}")
        logger.event(
            f"options: quality={options.quality} matcher={options.matcher} "
            f"backend={options.backend} dry_run={options.dry_run}"
        )

        if source.is_file() and source.suffix.lower() in VIDEO_EXTENSIONS:
            frame_command = build_frame_extraction_command(source, layout["frames"], options.quality)
            run_or_print(frame_command, options.dry_run, "Extract frames", logger=logger)
        elif source.is_dir():
            copied = stage_image_folder(source, layout["frames"], options.dry_run)
            print(f"Staged {copied} source images.")
            logger.event(f"Staged {copied} source images.")
        else:
            print(f"Unsupported source type: {source}")
            logger.event(f"Unsupported source type: {source}")
            return 2

        colmap_commands = build_colmap_commands(layout, options.matcher)
        for label, command in colmap_commands:
            run_or_print(command, options.dry_run, label, logger=logger)

        if not options.dry_run:
            validate_colmap_reconstruction(layout, logger=logger)

        if backend is not None:
            prepare_backend_dataset(layout, options.dry_run)
            plan = backend.build_plan(layout, options.quality)
            run_or_print(plan.command, options.dry_run, plan.label, logger=logger)
            if not options.dry_run and not plan.expected_output.exists():
                raise RuntimeError(
                    f"{backend.name} finished but did not create expected output: "
                    f"{plan.expected_output}"
                )

        write_manifest(source, layout, options, missing_tools)
        write_next_steps(layout)
        logger.event(f"SplatfastK1 project ready: {output}")

    print()
    print(f"SplatfastK1 project ready: {output}")
    print("Next: import splat/scene.ply in Blender.")
    return 0


def get_backend(name: str) -> SplatBackend | None:
    if name == "none":
        return None
    if name == "brush":
        return BrushBackend()
    raise ValueError(f"Unknown backend: {name}")


def get_missing_required_tools(required_tools: set[str]) -> list[str]:
    statuses = {status.name: status for status in collect_diagnostics()}
    return [
        tool
        for tool in sorted(required_tools)
        if tool in statuses and not statuses[tool].found
    ]


def make_layout(output: Path) -> dict[str, Path]:
    return {
        "root": output,
        "frames": output / "images",
        "reconstruction": output / "reconstruction",
        "database": output / "reconstruction" / "database.db",
        "sparse": output / "reconstruction" / "sparse",
        "backend_sparse": output / "sparse",
        "splat": output / "splat",
        "blender": output / "blender",
        "logs": output / "logs",
    }


def create_directories(layout: dict[str, Path]) -> None:
    for key, path in layout.items():
        if key == "database":
            continue
        path.mkdir(parents=True, exist_ok=True)


def remove_stale_metadata(layout: dict[str, Path]) -> None:
    # Older dry-runs may leave project metadata in the dataset root. Brush 0.2 can
    # mistake arbitrary JSON files for dataset manifests, so remove our metadata
    # before training and write it again after the backend finishes.
    for filename in ("splatforge.json", "NEXT_STEPS.md"):
        path = layout["root"] / filename
        if path.exists() and path.is_file():
            path.unlink()


def _read_bin_count(path: Path) -> int:
    """Return the record count from the uint64 header of a COLMAP .bin file."""
    with open(path, "rb") as fid:
        (count,) = struct.unpack("<Q", fid.read(8))
    return count


def validate_colmap_reconstruction(layout: dict[str, Path], logger: PipelineLogger | None = None) -> None:
    """Raise RuntimeError if the COLMAP sparse model is absent or too sparse to be useful."""
    sparse_0 = layout["sparse"] / "0"
    if not sparse_0.exists():
        raise RuntimeError(
            "COLMAP mapper did not produce a sparse model (sparse/0/ is missing). "
            "The input frames may have too little overlap or texture. "
            "Use a static scene with a moving camera."
        )

    registered = _read_bin_count(sparse_0 / "images.bin")
    total = sum(
        1 for f in layout["frames"].iterdir()
        if f.suffix.lower() in IMAGE_EXTENSIONS
    )
    points = _read_bin_count(sparse_0 / "points3D.bin")
    if logger:
        logger.event(f"VALIDATION: registered={registered}/{total} points3D={points}")
    if registered < MIN_REGISTERED_IMAGES:
        raise RuntimeError(
            f"COLMAP only registered {registered}/{total} frames. "
            "This video is not suitable for reconstruction. "
            "Use a static scene with a moving camera."
        )
    if points < MIN_POINTS3D:
        raise RuntimeError(
            f"COLMAP registered {registered}/{total} frames but only reconstructed "
            f"{points} 3D points (minimum {MIN_POINTS3D}). "
            "The scene lacks sufficient texture or overlap. "
            "Use a static scene with a moving camera."
        )


def prepare_backend_dataset(layout: dict[str, Path], dry_run: bool) -> None:
    source_sparse = layout["sparse"]
    target_sparse = layout["backend_sparse"]
    if dry_run:
        print(f"[Prepare backend dataset] {source_sparse} -> {target_sparse}")
        return
    if not source_sparse.exists():
        raise RuntimeError(f"COLMAP sparse output was not created: {source_sparse}")
    if target_sparse.exists():
        shutil.rmtree(target_sparse)
    shutil.copytree(source_sparse, target_sparse)


def build_frame_extraction_command(source: Path, frames_dir: Path, quality: str) -> list[str]:
    preset = QUALITY_PRESETS[quality]
    scale = f"scale='min({preset['max_size']},iw)':-2"
    return [
        command_for_tool("ffmpeg"),
        "-y",
        "-i",
        str(source),
        "-vf",
        f"fps={preset['fps']},{scale}",
        str(frames_dir / "frame_%06d.jpg"),
    ]


def stage_image_folder(source: Path, frames_dir: Path, dry_run: bool) -> int:
    images = sorted(path for path in source.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS)
    if dry_run:
        for image in images:
            print(f"[Stage image] {image} -> {frames_dir / image.name}")
        return len(images)

    for image in images:
        shutil.copy2(image, frames_dir / image.name)
    return len(images)


def build_colmap_commands(layout: dict[str, Path], matcher: str) -> list[tuple[str, list[str]]]:
    matcher_command = "exhaustive_matcher" if matcher == "exhaustive" else "sequential_matcher"
    colmap = command_for_tool("colmap")
    glomap = resolve_tool("glomap")
    mapper_label = "GLOMAP reconstruction" if glomap else "COLMAP reconstruction fallback"
    mapper_command = [glomap, "mapper"] if glomap else [colmap, "mapper"]
    # SiftMatching defaults assume a discrete GPU with plenty of VRAM. On
    # integrated graphics / low-end NVIDIA / older Intel HD, the matcher
    # fails with "Not enough GPU memory to match N features" and the whole
    # pipeline dies because there are no matches for the mapper to use.
    #
    # Force CPU matching with --SiftMatching.use_gpu 0. Slightly slower
    # (a few seconds for typical 22-90 frame runs), but works on every
    # machine. The Brush training step is where the real GPU work happens
    # anyway, not COLMAP matching.
    sift_cpu_only = [
        "--SiftMatching.use_gpu", "0",
    ]
    return [
        (
            "COLMAP feature extraction",
            [
                colmap,
                "feature_extractor",
                "--database_path",
                str(layout["database"]),
                "--image_path",
                str(layout["frames"]),
                "--ImageReader.single_camera",
                "1",
                "--ImageReader.camera_model",
                "SIMPLE_RADIAL",
                # Also force feature extraction to CPU — same VRAM concern
                "--SiftExtraction.use_gpu", "0",
            ],
        ),
        (
            f"COLMAP {matcher.replace('_', ' ')} matching",
            [
                colmap,
                matcher_command,
                "--database_path",
                str(layout["database"]),
                *sift_cpu_only,
            ],
        ),
        (
            mapper_label,
            [
                *mapper_command,
                "--database_path",
                str(layout["database"]),
                "--image_path",
                str(layout["frames"]),
                "--output_path",
                str(layout["sparse"]),
            ],
        ),
    ]


def run_or_print(
    command: list[str],
    dry_run: bool,
    label: str,
    logger: PipelineLogger | None = None,
) -> None:
    printable = " ".join(f'"{part}"' if " " in part else part for part in command)
    if dry_run:
        print(f"[{label}] {printable}")
        if logger:
            logger.event(f"DRY_RUN [{label}] {printable}")
        return

    print(f"[{label}]")
    # CREATE_NO_WINDOW (Windows only) prevents each subprocess (ffmpeg, COLMAP
    # feature/match/reconstruct, Brush) from spawning its own console window
    # when our app runs under pythonw.exe. Without this the user sees a flash
    # of black terminals between stages. On non-Windows this attribute doesn't
    # exist, getattr returns 0 which is a no-op.
    no_window_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if logger is None:
        # No logger: stream subprocess output directly to our stdout/stderr (legacy behaviour).
        result = subprocess.run(command, check=False, creationflags=no_window_flags)
        returncode = result.returncode
    else:
        logger.stage_start(label, command)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=no_window_flags,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            logger.subprocess_line(line)
        returncode = process.wait()
        logger.stage_end(label, returncode)
    if returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {returncode}: {printable}")


def write_manifest(
    source: Path,
    layout: dict[str, Path],
    options: CreateOptions,
    missing_tools: list[str],
) -> None:
    manifest = {
        "schema": "splatforge.project.v1",
        "source": str(source),
        "quality": options.quality,
        "matcher": options.matcher,
        "backend": options.backend,
        "paths": {key: str(path) for key, path in layout.items()},
        "missing_tools_at_creation": missing_tools,
        "outputs": {
            "gaussian_splat_ply": str(layout["splat"] / "scene.ply"),
            "blender_file": str(layout["blender"] / "scene.blend"),
        },
    }
    (layout["root"] / "splatforge.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def write_next_steps(layout: dict[str, Path]) -> None:
    text = """# Next Steps

This folder is ready for Blender handoff.

Expected final asset:

```text
splat/scene.ply
```

Open Blender, install the SplatfastK1 add-on, and import this project folder.
"""
    (layout["root"] / "NEXT_STEPS.md").write_text(text, encoding="utf-8")
