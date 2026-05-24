"""SplatfastK1 — Settings page.

Cloud training: paste your Replicate API key, click Test, click Save.
About: version + open output folder.
"""
from __future__ import annotations

import os
import webbrowser
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFrame,
    QScrollArea,
)

from desktop import config
from desktop.cloud import test_connection, ReplicateError


APP_VERSION = "0.1.0"


class _TestConnectionThread(QThread):
    """Background thread that calls Replicate so we don't block the UI."""

    ok = pyqtSignal(str)       # username
    failed = pyqtSignal(str)   # error message

    def __init__(self, api_key: str) -> None:
        super().__init__()
        self._api_key = api_key

    def run(self) -> None:
        try:
            info = test_connection(self._api_key)
            self.ok.emit(info.username)
        except ReplicateError as e:
            self.failed.emit(str(e))


class SettingsView(QWidget):
    """Settings page — cloud auth + about."""

    def __init__(self) -> None:
        super().__init__()
        self._test_thread: _TestConnectionThread | None = None

        # Wrap the content in a QScrollArea so adding new sections never
        # squeezes existing widgets (the bug that hid button text when we
        # added the Dependencies section).
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
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(28)

        # Header row: page title + connection status badge
        header = QHBoxLayout()
        title = QLabel("Settings")
        title.setObjectName("H1")
        header.addWidget(title)
        header.addStretch(1)
        self.status_badge = QLabel("Not connected")
        self.status_badge.setObjectName("BadgeMuted")
        header.addWidget(self.status_badge)
        root.addLayout(header)

        # --- Cloud training section ---
        cloud_title = QLabel("Cloud training")
        cloud_title.setObjectName("SectionTitle")
        root.addWidget(cloud_title)

        cloud_desc = QLabel(
            "Train on cloud GPUs (~6 minutes per splat) instead of this laptop "
            "(~80 minutes). Paste your Replicate API key to enable."
        )
        cloud_desc.setObjectName("Lede")
        cloud_desc.setWordWrap(True)
        root.addWidget(cloud_desc)

        # Field + buttons row
        key_label = QLabel("Replicate API key")
        key_label.setStyleSheet("font-weight: 600;")
        root.addWidget(key_label)

        field_row = QHBoxLayout()
        field_row.setSpacing(8)
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("r8_••••••••••••••••••••")
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setMinimumHeight(38)
        field_row.addWidget(self.key_input, 1)

        self.show_btn = QPushButton("Show")
        self.show_btn.setObjectName("Secondary")
        self.show_btn.setCheckable(True)
        self.show_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_btn.clicked.connect(self._toggle_show)
        field_row.addWidget(self.show_btn)

        self.test_btn = QPushButton("Test")
        self.test_btn.setObjectName("Secondary")
        self.test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.test_btn.clicked.connect(self._on_test)
        field_row.addWidget(self.test_btn)

        root.addLayout(field_row)

        # Helper link
        helper_row = QHBoxLayout()
        helper_label = QLabel("Get your key →")
        helper_label.setObjectName("Hint")
        link_btn = QPushButton("replicate.com/account/api-tokens")
        link_btn.setObjectName("Subtle")
        link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        link_btn.clicked.connect(
            lambda: webbrowser.open("https://replicate.com/account/api-tokens")
        )
        helper_row.addWidget(helper_label)
        helper_row.addWidget(link_btn)
        helper_row.addStretch(1)
        root.addLayout(helper_row)

        # Test result line — green/red text
        self.test_result = QLabel("")
        self.test_result.setObjectName("TestResult")
        self.test_result.setWordWrap(True)
        root.addWidget(self.test_result)

        # Save + Clear buttons
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.clear_btn = QPushButton("Clear saved key")
        self.clear_btn.setObjectName("Subtle")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self._on_clear)
        save_row.addWidget(self.clear_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("Primary")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(self._on_save)
        save_row.addWidget(self.save_btn)
        root.addLayout(save_row)

        # Divider
        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setObjectName("Rule")
        root.addWidget(rule)

        # --- Setup / dependencies ---
        deps_title = QLabel("Dependencies")
        deps_title.setObjectName("SectionTitle")
        root.addWidget(deps_title)

        deps_hint = QLabel(
            "Re-check or re-install the external tools SplatfastK1 needs "
            "(Brush binary, BlendSplat library, COLMAP, etc.)."
        )
        deps_hint.setObjectName("Hint")
        deps_hint.setWordWrap(True)
        root.addWidget(deps_hint)

        self.rerun_setup_btn = QPushButton("Re-run setup")
        self.rerun_setup_btn.setObjectName("Secondary")
        self.rerun_setup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rerun_setup_btn.clicked.connect(self._on_rerun_setup)
        root.addWidget(self.rerun_setup_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Divider
        rule2 = QFrame()
        rule2.setFrameShape(QFrame.Shape.HLine)
        rule2.setObjectName("Rule")
        root.addWidget(rule2)

        # --- About ---
        about_title = QLabel("About")
        about_title.setObjectName("SectionTitle")
        root.addWidget(about_title)

        ver = QLabel(f"SplatfastK1 v{APP_VERSION}")
        root.addWidget(ver)

        out_row = QHBoxLayout()
        out_label = QLabel("Output folder")
        out_label.setObjectName("Hint")
        out_row.addWidget(out_label)
        self.out_path = QLabel(str(config.get_outputs_dir()))
        out_row.addWidget(self.out_path, 1)
        open_out_btn = QPushButton("Open")
        open_out_btn.setObjectName("Secondary")
        open_out_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_out_btn.clicked.connect(self._on_open_outputs)
        out_row.addWidget(open_out_btn)
        root.addLayout(out_row)

        root.addStretch(1)

        # On first show, populate from saved state
        self.refresh_from_storage()

    # ----- Public -----

    def refresh_from_storage(self) -> None:
        """Reload UI state from keyring + prefs. Called when the view is shown."""
        token = config.get_replicate_token() or ""
        self.key_input.setText(token)
        if token:
            self._set_badge_connected()
            self.test_result.setText("Saved. Click Test to re-verify.")
            self.test_result.setStyleSheet("color: #6b6b6b;")
        else:
            self._set_badge_not_connected()
            self.test_result.setText("")

    # ----- UI handlers -----

    def _toggle_show(self) -> None:
        if self.show_btn.isChecked():
            self.key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_btn.setText("Hide")
        else:
            self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_btn.setText("Show")

    def _on_test(self) -> None:
        key = self.key_input.text().strip()
        if not key:
            self.test_result.setText("Paste an API key first.")
            self.test_result.setStyleSheet("color: #c00000;")
            return
        self.test_btn.setEnabled(False)
        self.test_btn.setText("Testing…")
        self.test_result.setText("Contacting Replicate…")
        self.test_result.setStyleSheet("color: #6b6b6b;")

        self._test_thread = _TestConnectionThread(key)
        self._test_thread.ok.connect(self._on_test_ok)
        self._test_thread.failed.connect(self._on_test_failed)
        self._test_thread.start()

    def _on_test_ok(self, username: str) -> None:
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Test")
        self.test_result.setText(f"Connected as {username}")
        self.test_result.setStyleSheet("color: #1f7a1f;")
        self._set_badge_connected()

    def _on_test_failed(self, message: str) -> None:
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Test")
        self.test_result.setText(message)
        self.test_result.setStyleSheet("color: #c00000;")
        self._set_badge_not_connected()

    def _on_save(self) -> None:
        key = self.key_input.text().strip()
        if not key:
            self.test_result.setText("Paste an API key first.")
            self.test_result.setStyleSheet("color: #c00000;")
            return
        config.set_replicate_token(key)
        self.test_result.setText("Saved to Windows Credential Manager.")
        self.test_result.setStyleSheet("color: #1f7a1f;")
        self._set_badge_connected()

    def _on_clear(self) -> None:
        config.clear_replicate_token()
        self.key_input.clear()
        self.test_result.setText("Saved key removed.")
        self.test_result.setStyleSheet("color: #6b6b6b;")
        self._set_badge_not_connected()

    def _on_rerun_setup(self) -> None:
        """Bubble up to MainWindow to re-show the Setup page."""
        # Walk up the parent chain to find MainWindow (which has show_setup())
        w = self.parent()
        while w is not None and not hasattr(w, "show_setup"):
            w = w.parent()
        if w is not None:
            w.show_setup()

    def _on_open_outputs(self) -> None:
        path = config.get_outputs_dir()
        try:
            os.startfile(str(path))
        except Exception:
            pass

    # ----- Badge helpers -----

    def _set_badge_connected(self) -> None:
        self.status_badge.setText("Connected")
        self.status_badge.setObjectName("BadgeOk")
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

    def _set_badge_not_connected(self) -> None:
        self.status_badge.setText("Not connected")
        self.status_badge.setObjectName("BadgeMuted")
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
