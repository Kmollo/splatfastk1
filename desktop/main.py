"""SplatfastK1 Desktop — entry point."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from desktop.widgets.main_window import MainWindow


def _set_windows_app_user_model_id(app_id: str) -> None:
    """Tell Windows this is its own app so the taskbar uses our icon, not Python's.

    Note: Microsoft Store Python silently ignores this call (it runs in a
    sandbox). For Store Python users we fall back to the win32 WM_SETICON
    approach below, which sets the icon at the window-handle level and
    usually works around the sandbox limitation.
    """
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def _force_taskbar_icon_win32(hwnd: int, icon_path: Path) -> None:
    """Force the Windows taskbar icon by calling SendMessage(WM_SETICON) directly.

    Why this exists: pythonw.exe ships with its own embedded icon. Even after
    SetWindowIcon() from Qt + the AppUserModelID, the Windows shell sometimes
    keeps showing the Python icon (especially under Microsoft Store Python,
    where the process is sandboxed). This bypasses all of that by writing the
    icon handle straight onto the window's WM_SETICON slot.

    Best-effort — silently fails on non-Windows or if the icon can't be loaded.
    """
    try:
        import ctypes
        from ctypes import wintypes

        # LoadImageW flags
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        LR_DEFAULTSIZE = 0x0040
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1

        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.SendMessageW.restype = ctypes.c_void_p

        # Load big icon (32x32 typical) and small icon (16x16 typical)
        big = user32.LoadImageW(
            None, str(icon_path), IMAGE_ICON, 32, 32,
            LR_LOADFROMFILE,
        )
        small = user32.LoadImageW(
            None, str(icon_path), IMAGE_ICON, 16, 16,
            LR_LOADFROMFILE,
        )
        if big:
            user32.SendMessageW(int(hwnd), WM_SETICON, ICON_BIG, big)
        if small:
            user32.SendMessageW(int(hwnd), WM_SETICON, ICON_SMALL, small)
    except Exception:
        pass  # Icon is cosmetic — never let it crash the app


def main() -> int:
    # Set AppUserModelID BEFORE creating QApplication so the taskbar icon is
    # right under normal python.org Python. Under Microsoft Store Python this
    # is silently ignored — we cover that case via win32 WM_SETICON below.
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

    # AFTER show() — force the taskbar icon at the win32 layer too. This is the
    # belt-and-suspenders fix for Microsoft Store Python and other sandboxed
    # Python distributions where the process-level icon settings get ignored.
    if icon_path.exists() and sys.platform == "win32":
        try:
            hwnd = int(window.winId())
            _force_taskbar_icon_win32(hwnd, icon_path)
        except Exception:
            pass

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
