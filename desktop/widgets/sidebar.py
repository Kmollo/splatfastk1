"""SplatfastK1 left sidebar — brand at top, nav items below."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
)


# Page keys — the main window listens for these and swaps content
PAGE_HOME = "home"
PAGE_SETTINGS = "settings"
PAGE_PROJECTS = "projects"


class Sidebar(QWidget):
    """Left navigation. Emits `nav` with one of the PAGE_* constants on click."""

    nav = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedWidth(220)
        self.setObjectName("Sidebar")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 20, 16, 16)
        root.setSpacing(20)

        # Nav items — Home, Settings, Projects (Home replaces the old brand header)
        nav_box = QVBoxLayout()
        nav_box.setSpacing(4)

        self._nav_buttons: dict[str, QPushButton] = {}

        for key, label in [
            (PAGE_HOME, "Home"),
            (PAGE_SETTINGS, "Settings"),
            (PAGE_PROJECTS, "Projects"),
        ]:
            btn = QPushButton(label)
            btn.setObjectName("NavItem")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, k=key: self._select(k))
            nav_box.addWidget(btn)
            self._nav_buttons[key] = btn

        root.addLayout(nav_box)
        root.addStretch(1)

        # Bottom — version
        ver = QLabel("v0.1.0")
        ver.setObjectName("Version")
        ver.setAlignment(Qt.AlignmentFlag.AlignLeft)
        root.addWidget(ver)

    def _select(self, page_key: str) -> None:
        for k, b in self._nav_buttons.items():
            b.setChecked(k == page_key)
        self.nav.emit(page_key)

    def set_active(self, page_key: str) -> None:
        """Called by main window when navigation happens from elsewhere."""
        for k, b in self._nav_buttons.items():
            b.setChecked(k == page_key)
