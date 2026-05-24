import struct
from pathlib import Path

import pytest

from splatforge.pipeline import (
    build_colmap_commands,
    build_frame_extraction_command,
    get_backend,
    make_layout,
    prepare_backend_dataset,
    remove_stale_metadata,
    validate_colmap_reconstruction,
)


def _make_bin(path: Path, count: int) -> None:
    """Write a minimal COLMAP .bin file with the given record count header."""
    path.write_bytes(struct.pack("<Q", count))


def test_frame_extraction_command_uses_quality_preset(tmp_path):
    command = build_frame_extraction_command(
        Path("input.mp4"),
        tmp_path / "frames",
        "fast",
    )

    assert command[0].lower().endswith(("ffmpeg", "ffmpeg.exe"))
    assert any("fps=1" in part for part in command)
    assert str(tmp_path / "frames" / "frame_%06d.jpg") in command


def test_layout_contains_blender_handoff_folder(tmp_path):
    layout = make_layout(tmp_path / "project")

    assert layout["frames"] == tmp_path / "project" / "images"
    assert layout["splat"] == tmp_path / "project" / "splat"
    assert layout["blender"] == tmp_path / "project" / "blender"
    assert layout["backend_sparse"] == tmp_path / "project" / "sparse"


def test_colmap_commands_switch_matcher(tmp_path):
    layout = make_layout(tmp_path / "project")
    commands = build_colmap_commands(layout, "exhaustive")

    assert commands[1][1][1] == "exhaustive_matcher"
    assert "reconstruction" in commands[2][0].lower()
    assert "--ImageReader.single_camera" in commands[0][1]


def test_brush_backend_exports_scene_ply(tmp_path):
    layout = make_layout(tmp_path / "project")
    backend = get_backend("brush")

    plan = backend.build_plan(layout)

    assert plan.command[1] == str(layout["root"])
    assert "--export-path" in plan.command
    assert plan.expected_output == layout["splat"] / "scene.ply"


def test_remove_stale_metadata_removes_project_json(tmp_path):
    layout = make_layout(tmp_path / "project")
    layout["root"].mkdir(parents=True)
    manifest = layout["root"] / "splatforge.json"
    manifest.write_text("{}", encoding="utf-8")

    remove_stale_metadata(layout)

    assert not manifest.exists()


def test_prepare_backend_dataset_copies_sparse_folder(tmp_path):
    layout = make_layout(tmp_path / "project")
    sparse_model = layout["sparse"] / "0"
    sparse_model.mkdir(parents=True)
    (sparse_model / "cameras.bin").write_text("camera", encoding="utf-8")

    prepare_backend_dataset(layout, dry_run=False)

    assert (layout["backend_sparse"] / "0" / "cameras.bin").exists()


def test_validate_colmap_reconstruction_passes(tmp_path):
    layout = make_layout(tmp_path / "project")
    sparse_0 = layout["sparse"] / "0"
    sparse_0.mkdir(parents=True)
    _make_bin(sparse_0 / "images.bin", 10)
    _make_bin(sparse_0 / "points3D.bin", 100)
    layout["frames"].mkdir(parents=True)
    for i in range(10):
        (layout["frames"] / f"frame_{i:06d}.jpg").write_bytes(b"")

    validate_colmap_reconstruction(layout)  # must not raise


def test_validate_colmap_reconstruction_no_sparse_dir(tmp_path):
    layout = make_layout(tmp_path / "project")
    layout["frames"].mkdir(parents=True)

    with pytest.raises(RuntimeError, match="sparse/0/ is missing"):
        validate_colmap_reconstruction(layout)


def test_validate_colmap_reconstruction_too_few_images(tmp_path):
    layout = make_layout(tmp_path / "project")
    sparse_0 = layout["sparse"] / "0"
    sparse_0.mkdir(parents=True)
    _make_bin(sparse_0 / "images.bin", 2)
    _make_bin(sparse_0 / "points3D.bin", 200)
    layout["frames"].mkdir(parents=True)
    for i in range(52):
        (layout["frames"] / f"frame_{i:06d}.jpg").write_bytes(b"")

    with pytest.raises(RuntimeError, match="registered 2/52 frames"):
        validate_colmap_reconstruction(layout)


def test_validate_colmap_reconstruction_too_few_points(tmp_path):
    layout = make_layout(tmp_path / "project")
    sparse_0 = layout["sparse"] / "0"
    sparse_0.mkdir(parents=True)
    _make_bin(sparse_0 / "images.bin", 10)
    _make_bin(sparse_0 / "points3D.bin", 20)
    layout["frames"].mkdir(parents=True)
    for i in range(10):
        (layout["frames"] / f"frame_{i:06d}.jpg").write_bytes(b"")

    with pytest.raises(RuntimeError, match="20 3D points"):
        validate_colmap_reconstruction(layout)
