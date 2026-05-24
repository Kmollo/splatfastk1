"""SplatfastK1 Desktop — entry point."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from desktop.widgets.main_window import MainWindow


def _set_windows_app_user_model_id(app_id: str) -> None:
    """Tell Windows this is its own app so the taskbar uses our icon, not Python's."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def main() -> int:
    # Set this BEFORE creating the QApplication so the taskbar icon is right
    _set_windows_app_user_model_id("SplatfastK1.Desktop.1")

    app = QApplication(sys.argv)
    app.setApplicationName("SplatfastK1")
    app.setOrganizationName("SplatfastK1")

    # App-wide icon
    icon_path = Path(__file__).parent / "icons" / "splatforge.ico"
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        app.setWindowIcon(icon)

    # Load global stylesheet
    qss = (Path(__file__).parent / "style.qss").read_text(encoding="utf-8")
    app.setStyleSheet(qss)

    window = MainWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
