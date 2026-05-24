"""SplatfastK1 first-launch setup view.

Shown automatically when the app starts if any REQUIRED dependency is missing
(Brush binary, BlendSplat library, COLMAP). User clicks one button to install
the things we can auto-install; optional deps (Blender, Replicate key) get
"Open page" buttons instead.

Once all required deps are OK, the "Continue to Home" button enables.
"""
from __future__ import annotations

import webbrowser
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QProgressBar,
    QScrollArea,
)

from desktop import setup_helpers as sh


# ---------------------------------------------------------------------------
# Background worker — runs the slow installers off the UI thread
# ---------------------------------------------------------------------------

class _InstallWorker(QThread):
    """Runs the auto-installers sequentially and reports progress."""

    progress = pyqtSignal(int, str)        # 0..100, message
    step_done = pyqtSignal(str, bool, str) # dep_name, success, detail
    all_done = pyqtSignal(bool)            # True if every step succeeded

    def run(self) -> None:
        steps = [
            ("Brush binary",       sh.install_brush,       sh.check_brush),
            ("BlendSplat library", sh.install_blendsplat,  sh.check_blendsplat),
            ("COLMAP",             sh.install_colmap,      sh.check_colmap),
        ]
        all_ok = True
        for i, (name, installer, checker) in enumerate(steps):
            # Skip ones that are already installed
            if checker()[0] == sh.STATUS_OK:
                self.step_done.emit(name, True, "Already installed")
                continue
            # Scope the progress callback so the bar's 0-100 maps into this
            # step's slice of the overall progress.
            base = int(i * 100 / len(steps))
            span = int(100 / len(steps))

            def cb(pct: int, msg: str, base=base, span=span):
                overall = base + int(pct * span / 100)
                self.progress.emit(overall, msg)

            ok, detail = installer(cb)
            self.step_done.emit(name, ok, detail)
            if not ok:
                all_ok = False
        self.progress.emit(100, "Done" if all_ok else "Some installs failed")
        self.all_done.emit(all_ok)


# ---------------------------------------------------------------------------
# A single status row (checkmark + name + detail)
# ---------------------------------------------------------------------------

class _DepRow(QFrame):
    def __init__(self, name: str, required: bool) -> None:
        super().__init__()
        self.setObjectName("DepRow")
        # Force enough vertical space so descenders (p, g, y) in the labels
        # don't get clipped when many rows stack into a tight layout.
        self.setMinimumHeight(28)
        self.name = name
        self.required = required
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(10)

        self.icon = QLabel("?")
        self.icon.setFixedWidth(20)
        self.icon.setMinimumHeight(20)
        h.addWidget(self.icon)

        name_label = QLabel(name + ("" if required else "  (optional)"))
        name_label.setStyleSheet("font-weight: 600;")
        name_label.setMinimumHeight(20)
        h.addWidget(name_label)

        self.detail = QLabel("")
        self.detail.setObjectName("Hint")
        self.detail.setMinimumHeight(20)
        h.addWidget(self.detail, 1)

    def set_status(self, status: str, detail: str) -> None:
        if status == sh.STATUS_OK:
            self.icon.setText("✓")
            self.icon.setStyleSheet("color: #1c7a1c; font-weight: 700;")
        elif status == sh.STATUS_MISSING:
            self.icon.setText("✗")
            self.icon.setStyleSheet("color: #b00020; font-weight: 700;")
        else:  # STATUS_MANUAL
            self.icon.setText("!")
            self.icon.setStyleSheet("color: #b07000; font-weight: 700;")
        self.detail.setText(detail)


# ---------------------------------------------------------------------------
# The full Setup page
# ---------------------------------------------------------------------------

class SetupView(QWidget):
    """First-launch dependency installer.

    Emits ``continue_to_home`` when the user finishes (either everything is
    installed, or they explicitly skipped the optional deps).
    """

    continue_to_home = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._worker: Optional[_InstallWorker] = None

        # Wrap content in a scroll area for the same future-proofing as Settings
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(48, 40, 48, 40)
        root.setSpacing(20)

        title = QLabel("First-time setup")
        title.setObjectName("H1")
        root.addWidget(title)

        intro = QLabel(
            "We need a few things on your computer before you can turn "
            "videos into Gaussian splats. Click the button below — I'll "
            "install everything I can. The two optional items (Blender + "
            "Replicate account) you can do later from Settings."
        )
        intro.setWordWrap(True)
        intro.setObjectName("Hint")
        root.addWidget(intro)

        # Status list
        self._rows: dict[str, _DepRow] = {}
        rows_box = QVBoxLayout()
        rows_box.setSpacing(2)
        for name, status, detail, required in sh.summarize_all():
            row = _DepRow(name, required)
            row.set_status(status, detail)
            self._rows[name] = row
            rows_box.addWidget(row)
        root.addLayout(rows_box)

        root.addSpacing(4)

        # ---- Install button — CENTERED with max width so it doesn't span ----
        self.install_btn = QPushButton("Install everything I can")
        self.install_btn.setObjectName("Primary")
        self.install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_btn.setMinimumWidth(280)
        self.install_btn.setMaximumWidth(360)
        self.install_btn.clicked.connect(self._on_install_clicked)
        install_row = QHBoxLayout()
        install_row.addStretch(1)
        install_row.addWidget(self.install_btn)
        install_row.addStretch(1)
        root.addLayout(install_row)

        # ---- Thin progress bar + caption — only visible while installing ----
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        self.progress.setTextVisible(False)
        self.progress.setMaximumWidth(420)
        prog_row = QHBoxLayout()
        prog_row.addStretch(1)
        prog_row.addWidget(self.progress)
        prog_row.addStretch(1)
        root.addLayout(prog_row)

        self.progress_label = QLabel("")
        self.progress_label.setObjectName("Hint")
        self.progress_label.setVisible(False)
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.progress_label)

        # ---- Success callout (shown after a successful install run) ----
        self.success_callout = QLabel("✓ All required items installed")
        self.success_callout.setObjectName("SuccessCallout")
        self.success_callout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.success_callout.setVisible(False)
        success_row = QHBoxLayout()
        success_row.addStretch(1)
        success_row.addWidget(self.success_callout, 1)
        success_row.addStretch(1)
        root.addLayout(success_row)

        # Auto-hide the progress bar a couple seconds after a successful run
        # so it doesn't keep dominating the visual space.
        self._progress_hide_timer = QTimer(self)
        self._progress_hide_timer.setSingleShot(True)
        self._progress_hide_timer.timeout.connect(self._hide_progress)

        root.addSpacing(8)

        # ---- Optional manual links — Blender + Replicate ----
        optional_title = QLabel("Optional — open the page yourself:")
        optional_title.setStyleSheet("font-weight: 600;")
        root.addWidget(optional_title)

        blender_btn = QPushButton("Open Blender 5.1 download page")
        blender_btn.setObjectName("Secondary")
        blender_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        blender_btn.clicked.connect(
            lambda: webbrowser.open("https://www.blender.org/download/")
        )
        root.addWidget(blender_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        replicate_btn = QPushButton("Open Replicate signup (free)")
        replicate_btn.setObjectName("Secondary")
        replicate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        replicate_btn.clicked.connect(
            lambda: webbrowser.open("https://replicate.com/signin")
        )
        root.addWidget(replicate_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        root.addStretch(1)

        # ---- Continue button — CENTERED, primary ----
        self.continue_btn = QPushButton("Continue to Home")
        self.continue_btn.setObjectName("Primary")
        self.continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.continue_btn.setMinimumWidth(280)
        self.continue_btn.setMaximumWidth(360)
        self.continue_btn.clicked.connect(self._on_continue)
        continue_row = QHBoxLayout()
        continue_row.addStretch(1)
        continue_row.addWidget(self.continue_btn)
        continue_row.addStretch(1)
        root.addLayout(continue_row)
        self._refresh_continue_state()

    # ----- Public -----

    def refresh(self) -> None:
        """Re-scan disk + update every row. Called every time we show this page."""
        for name, status, detail, _required in sh.summarize_all():
            if name in self._rows:
                self._rows[name].set_status(status, detail)
        self._refresh_continue_state()

    # ----- Internal -----

    def _refresh_continue_state(self) -> None:
        ready = sh.all_required_ok()
        self.continue_btn.setEnabled(ready)
        if ready:
            self.continue_btn.setText("Continue to Home")
        else:
            self.continue_btn.setText("Install required items above first")

    def _on_install_clicked(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.install_btn.setEnabled(False)
        self.install_btn.setText("Installing...")
        self.success_callout.setVisible(False)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.progress_label.setVisible(True)
        self.progress_label.setText("Starting...")

        self._worker = _InstallWorker()
        self._worker.progress.connect(self._on_progress)
        self._worker.step_done.connect(self._on_step_done)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()

    @pyqtSlot(int, str)
    def _on_progress(self, pct: int, msg: str) -> None:
        self.progress.setValue(pct)
        self.progress_label.setText(msg)

    @pyqtSlot(str, bool, str)
    def _on_step_done(self, name: str, ok: bool, detail: str) -> None:
        if name in self._rows:
            self._rows[name].set_status(
                sh.STATUS_OK if ok else sh.STATUS_MISSING, detail
            )

    @pyqtSlot(bool)
    def _on_all_done(self, all_ok: bool) -> None:
        # Re-scan from disk so the rows reflect real on-disk state
        self.refresh()
        self.install_btn.setEnabled(True)
        self.install_btn.setText("Install everything I can")
        if all_ok:
            # Show green success callout, auto-hide the progress bar so the
            # giant black slab doesn't keep dominating the page.
            self.success_callout.setVisible(True)
            self.progress_label.setVisible(False)
            self._progress_hide_timer.start(2000)
        else:
            self.success_callout.setVisible(False)
            self.progress_label.setText(
                "Some items failed — see the messages above. Click 'Install' to retry."
            )

    def _hide_progress(self) -> None:
        self.progress.setVisible(False)
        self.progress_label.setVisible(False)

    def _on_continue(self) -> None:
        self.continue_to_home.emit()
