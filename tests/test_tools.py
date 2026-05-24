from splatforge.tools import command_for_tool, resolve_tool


def test_resolve_local_brush_app_windows(tmp_path):
    binary_dir = tmp_path / "references" / "skysplat_blender" / "binaries"
    binary_dir.mkdir(parents=True)
    brush = binary_dir / "brush_app_windows.exe"
    brush.write_text("", encoding="utf-8")

    assert resolve_tool("brush", tmp_path) == str(brush.resolve())


def test_command_falls_back_to_tool_name(tmp_path):
    assert command_for_tool("definitely_missing_tool", tmp_path) == "definitely_missing_tool"
