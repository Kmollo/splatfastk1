"""SplatfastK1 Desktop — Start screen (empty state / landing)."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal


class StartScreen(QWidget):
    """Empty-state landing page with a Start Project button."""

    start_clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 48, 48, 48)
        root.addStretch(1)

        title = QLabel("Turn a video into a Gaussian splat.")
        title.setObjectName("H1")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # No word-wrap on the title — keep it one line so layout heights are stable
        root.addWidget(title)

        root.addSpacing(24)

        # Lede — single short line, no word-wrap so Qt doesn't miscalculate height
        lede = QLabel("Open it in Blender when it's done.")
        lede.setObjectName("Lede")
        lede.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(lede)

        root.addSpacing(40)

        self.start_btn = QPushButton("Start a new project")
        self.start_btn.setObjectName("Primary")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setMinimumWidth(280)
        self.start_btn.clicked.connect(self.start_clicked.emit)
        root.addWidget(self.start_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        root.addSpacing(16)
        hint = QLabel("MP4, MOV, MKV, AVI, M4V, or WebM • 15-60s, camera moving around the subject")
        hint.setObjectName("Hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(hint)

        root.addStretch(2)
