"""Headless button verification — simulates every UI click and reports results.

Run with: python -m desktop.test_buttons
Exits 0 if all checks pass, 1 if any fail.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QPoint, QEvent, QMimeData, QUrl
from PyQt6.QtGui import QDropEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    # Load stylesheet just like main.py
    qss = (Path(__file__).parent / "style.qss").read_text(encoding="utf-8")
    app.setStyleSheet(qss)

    from desktop.widgets.main_window import MainWindow
    from desktop.widgets.sidebar import PAGE_SETTINGS, PAGE_PROJECTS, PAGE_HOME
    win = MainWindow()
    win.show()
    app.processEvents()

    results: list[tuple[str, bool, str]] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        results.append((name, cond, detail))

    # --- 1. Start screen -> Start button visible ---
    start_screen = win.start_screen
    check("StartScreen.start_btn exists", start_screen.start_btn is not None)
    check("StartScreen.start_btn enabled", start_screen.start_btn.isEnabled())

    # --- 2. Click Start button -> should go to project view (stack index 1) ---
    QTest.mouseClick(start_screen.start_btn, Qt.MouseButton.LeftButton)
    app.processEvents()
    check("Start button navigates to ProjectView",
          win.stack.currentWidget() is win.project_view,
          f"current = {type(win.stack.currentWidget()).__name__}")

    # --- 3. Project view setup page is active (stack index 0 inside ProjectView) ---
    pv = win.project_view
    check("ProjectView starts on setup page",
          pv.stack.currentIndex() == 0,
          f"inner stack index = {pv.stack.currentIndex()}")

    # --- 4. Train button is initially disabled (no video) ---
    check("Train button disabled before video", not pv.train_btn.isEnabled())

    # --- 5. Train hint is visible ---
    check("Train hint visible when no video", pv.train_hint.isVisible())

    # --- 6. Quality slider works -> label updates ---
    initial_label = pv.quality_value.text()
    pv.quality_slider.setValue(1)
    app.processEvents()
    check("Quality slider value=1 -> label = Balanced",
          pv.quality_value.text() == "Balanced",
          f"label = {pv.quality_value.text()}")
    pv.quality_slider.setValue(2)
    app.processEvents()
    check("Quality slider value=2 -> label = High",
          pv.quality_value.text() == "High",
          f"label = {pv.quality_value.text()}")
    pv.quality_slider.setValue(0)  # reset
    app.processEvents()

    # --- 7. Mode toggle: local is checked by default ---
    check("Local radio checked by default", pv.local_radio.isChecked())

    # --- 7b. Cloud radio state reflects API key presence ---
    from desktop import config as _cfg
    saved_token = _cfg.get_replicate_token()
    # No key path
    _cfg.clear_replicate_token()
    pv.reset()
    check("Cloud radio disabled when no API key",
          not pv.cloud_radio.isEnabled())
    check("Cloud label hints at Settings when disabled",
          "Settings" in pv.cloud_radio.text() or "settings" in pv.cloud_radio.text())
    # With key path
    _cfg.set_replicate_token("r8_PYTEST_DUMMY_FOR_RADIO_STATE_DELETE_ME")
    pv.reset()
    check("Cloud radio enabled when API key saved",
          pv.cloud_radio.isEnabled())
    check("Cloud label is clean when enabled",
          pv.cloud_radio.text() == "In the cloud")
    # Restore prior state
    _cfg.clear_replicate_token()
    if saved_token:
        _cfg.set_replicate_token(saved_token)
    pv.reset()

    # --- 8. Simulate setting a video path directly -> Train button should enable ---
    # Look for a test video in (a) an env var override, (b) the user's Downloads
    # folder (any .mp4). This used to be hardcoded to one dev's machine — the
    # path identified them. Now it gracefully skips if no video is present.
    test_video: Path | None = None
    env_override = os.environ.get("SPLATFORGE_TEST_VIDEO", "")
    if env_override and Path(env_override).exists():
        test_video = Path(env_override)
    else:
        downloads = Path.home() / "Downloads"
        if downloads.exists():
            mp4s = list(downloads.glob("*.mp4"))
            if mp4s:
                test_video = mp4s[0]
    if test_video is not None and test_video.exists():
        pv._set_video(test_video)
        app.processEvents()
        check("Project name auto-populated from video stem",
              pv.name_input.text() == test_video.stem,
              f"name = {pv.name_input.text()}")
        check("Train button enabled after video + name set", pv.train_btn.isEnabled())
        check("Drop label shows filename",
              pv.drop_label.text() == test_video.name,
              f"label = {pv.drop_label.text()}")
        check("Drop zone styled active",
              pv.drop_zone.objectName() == "DropZoneActive",
              f"objectName = {pv.drop_zone.objectName()}")
        # Clearing the name should disable the train button
        pv.name_input.setText("")
        app.processEvents()
        check("Train button disabled when name is empty",
              not pv.train_btn.isEnabled())
        pv.name_input.setText("test_project")
        app.processEvents()
        check("Train button re-enabled when name is provided",
              pv.train_btn.isEnabled())
    else:
        check("Test video exists at expected path", False,
              f"missing: {test_video}")

    # --- 9. Back button works — should return to start screen ---
    QTest.mouseClick(pv.back_btn, Qt.MouseButton.LeftButton)
    app.processEvents()
    check("Back button returns to StartScreen",
          win.stack.currentWidget() is win.start_screen,
          f"current = {type(win.stack.currentWidget()).__name__}")

    # --- 10. After back-and-forth, project view resets ---
    QTest.mouseClick(start_screen.start_btn, Qt.MouseButton.LeftButton)
    app.processEvents()
    check("Train button disabled again after reset",
          not pv.train_btn.isEnabled())
    check("Drop label reset to default",
          pv.drop_label.text() == "Drop a video here or click to choose")

    # --- 11. Done page buttons exist ---
    check("View Splat button exists", pv.view_brush_btn is not None)
    check("Open in Blender button exists", pv.open_blender_btn is not None)
    check("Show files button exists", pv.open_folder_btn is not None)
    check("Train Again button exists", hasattr(pv, "train_again_btn") and pv.train_again_btn is not None)
    check("Train Again has click handler",
          pv.train_again_btn.receivers(pv.train_again_btn.clicked) > 0)

    # --- 11b. load_completed() exists and jumps to Done page ---
    check("ProjectView has load_completed()", hasattr(pv, "load_completed"))
    # Use the bridge folder if it exists; otherwise just skip the runtime check
    from desktop import config as _cfg2
    sample_project = _cfg2.get_outputs_dir() / "4340824-hd_1920_1080_30fps"
    if sample_project.exists():
        pv.load_completed(sample_project)
        app.processEvents()
        check("load_completed switches to Done page (stack index 2)",
              pv.stack.currentIndex() == 2,
              f"stack idx = {pv.stack.currentIndex()}")
        check("load_completed sets output_dir",
              pv.output_dir is not None and pv.output_dir.resolve() == sample_project.resolve())
        check("load_completed sets _resuming_project_dir",
              pv._resuming_project_dir is not None)
        # Click Train Again -> should go back to setup page (index 0)
        QTest.mouseClick(pv.train_again_btn, Qt.MouseButton.LeftButton)
        app.processEvents()
        check("Train Again returns to setup page",
              pv.stack.currentIndex() == 0,
              f"stack idx = {pv.stack.currentIndex()}")
        pv.reset()

    # --- 12. Result button click handlers are connected ---
    # We can't actually click them without a real splat, but check they have handlers
    # by inspecting the signal's receivers
    try:
        check("View Splat button has handler",
              pv.view_brush_btn.receivers(pv.view_brush_btn.clicked) > 0)
    except Exception as e:
        check("View Splat button has handler", False, str(e))
    try:
        check("Open in Blender button has handler",
              pv.open_blender_btn.receivers(pv.open_blender_btn.clicked) > 0)
    except Exception as e:
        check("Open in Blender button has handler", False, str(e))

    # --- 13. Log toggle button connected to a handler ---
    if hasattr(pv, "log_toggle"):
        try:
            check("Log toggle has click handler",
                  pv.log_toggle.receivers(pv.log_toggle.clicked) > 0)
        except Exception as e:
            check("Log toggle has click handler", False, str(e))

    # --- 14. Sidebar exists with the right buttons ---
    sidebar = win.sidebar
    check("Sidebar Settings button exists", PAGE_SETTINGS in sidebar._nav_buttons)
    check("Sidebar Projects button exists", PAGE_PROJECTS in sidebar._nav_buttons)

    # --- 15. Sidebar nav swaps stack to Settings ---
    QTest.mouseClick(sidebar._nav_buttons[PAGE_SETTINGS], Qt.MouseButton.LeftButton)
    app.processEvents()
    check("Settings nav swaps to settings page",
          win.stack.currentWidget() is win.settings_view,
          f"current = {type(win.stack.currentWidget()).__name__}")

    # --- 16. Settings view has the required widgets ---
    sv = win.settings_view
    check("Settings has key input", sv.key_input is not None)
    check("Settings has Test button with handler",
          sv.test_btn is not None and sv.test_btn.receivers(sv.test_btn.clicked) > 0)
    check("Settings has Save button with handler",
          sv.save_btn is not None and sv.save_btn.receivers(sv.save_btn.clicked) > 0)
    check("Settings has Show toggle with handler",
          sv.show_btn is not None and sv.show_btn.receivers(sv.show_btn.clicked) > 0)
    check("Settings has Clear button with handler",
          sv.clear_btn is not None and sv.clear_btn.receivers(sv.clear_btn.clicked) > 0)

    # --- 17. Sidebar nav swaps stack to Projects ---
    QTest.mouseClick(sidebar._nav_buttons[PAGE_PROJECTS], Qt.MouseButton.LeftButton)
    app.processEvents()
    check("Projects nav swaps to projects page",
          win.stack.currentWidget() is win.projects_view,
          f"current = {type(win.stack.currentWidget()).__name__}")

    # --- 18. Config round-trip: save a dummy token then clear it ---
    from desktop import config
    pre = config.get_replicate_token()
    config.set_replicate_token("r8_PYTEST_DUMMY_DELETE_ME")
    check("Token round-trip: save then read",
          config.get_replicate_token() == "r8_PYTEST_DUMMY_DELETE_ME")
    config.clear_replicate_token()
    check("Token round-trip: cleared",
          config.get_replicate_token() is None)
    if pre:
        config.set_replicate_token(pre)  # restore user's actual token if present

    # --- Report ---
    print()
    print("=" * 60)
    print("Button verification results")
    print("=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    for name, ok, detail in results:
        mark = "[OK]" if ok else "[FAIL]"
        suffix = f" ({detail})" if detail and not ok else ""
        print(f"  {mark} {name}{suffix}")
    print("-" * 60)
    print(f"  {passed} passed, {failed} failed")
    print("=" * 60)

    win.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
