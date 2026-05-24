"""SplatfastK1 Desktop — Project view.

Lets the user pick a video, choose training settings, kick off training,
watch progress, and open the result in Brush or Blender.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QFrame,
    QSlider,
    QRadioButton,
    QButtonGroup,
    QStackedWidget,
    QProgressBar,
    QPlainTextEdit,
)

from desktop import config
from desktop.widgets.pipeline_worker import PipelineWorker
from desktop.widgets.cloud_worker import CloudPipelineWorker


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}

# Characters that aren't safe in a Windows folder name
_UNSAFE_NAME_CHARS = set('<>:"/\\|?*')


def _sanitize_project_name(name: str) -> str:
    """Return a filesystem-safe version of name.

    Strips Windows-unsafe chars, collapses whitespace, then replaces spaces
    with underscores. The underscore swap is important: COLMAP.bat (and
    several other batch-file wrappers in the toolchain) mis-parse paths that
    contain unescaped spaces, even when quoted at our subprocess level. The
    user types "My Cool Project", we make it 'My_Cool_Project' on disk.
    """
    cleaned = "".join(c for c in name if c not in _UNSAFE_NAME_CHARS).strip()
    # Collapse repeated whitespace and replace every run with a single underscore
    cleaned = "_".join(cleaned.split())
    return cleaned[:120]  # cap length for sanity

# Pipeline stages, used for the progress checklist + bar
STAGES = [
    ("upload", "Upload"),
    ("frames", "Extract frames"),
    ("features", "Find features"),
    ("match", "Match frames"),
    ("reconstruct", "Build 3D model"),
    ("splat", "Train splat"),
]


class ProjectView(QWidget):
    """Main working view — video picker → settings → train → result."""

    back_to_start = pyqtSignal()
    # Emitted when the user clicks "Continue in background" — main window
    # should navigate them to Home while keeping the worker alive.
    minimize_to_background = pyqtSignal()
    # Emitted when a training finishes/fails while the user has navigated
    # away from the project view. main window shows an in-app banner.
    training_finished_in_background = pyqtSignal(str, bool)  # (project_name, success)

    def __init__(self) -> None:
        super().__init__()
        self.video_path: Path | None = None
        self.output_dir: Path | None = None
        self.worker: PipelineWorker | None = None
        # Set by load_completed() when the user resumes an existing project.
        # Lets the user re-train into the same folder without a name-collision warning.
        self._resuming_project_dir: Path | None = None

        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 16, 32, 32)
        root.setSpacing(20)

        # Header row: back button + title
        header = QHBoxLayout()
        self.back_btn = QPushButton("← Back")
        self.back_btn.setObjectName("Subtle")
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.clicked.connect(self._on_back)
        header.addWidget(self.back_btn)
        header.addStretch(1)
        root.addLayout(header)

        # Stacked content — setup vs running vs done
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._setup_page = self._build_setup_page()
        self._run_page = self._build_run_page()
        self._done_page = self._build_done_page()

        self.stack.addWidget(self._setup_page)  # index 0
        self.stack.addWidget(self._run_page)    # index 1
        self.stack.addWidget(self._done_page)   # index 2

    # ----- Setup page -----

    def _build_setup_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(20)

        # Drop zone
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("DropZone")
        self.drop_zone.setMinimumHeight(160)
        dz = QVBoxLayout(self.drop_zone)
        dz.setContentsMargins(24, 24, 24, 24)
        dz.addStretch(1)
        plus = QLabel("+")
        plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plus.setStyleSheet("font-size: 30px; color: #000;")
        dz.addWidget(plus)
        self.drop_label = QLabel("Drop a video here or click to choose")
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        dz.addWidget(self.drop_label)
        hint = QLabel("MP4, MOV, MKV, AVI, M4V, or WebM")
        hint.setObjectName("Hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dz.addWidget(hint)
        dz.addStretch(1)
        self.drop_zone.mousePressEvent = self._click_drop_zone  # type: ignore[assignment]
        v.addWidget(self.drop_zone)

        # Project name row
        name_row = QHBoxLayout()
        name_label = QLabel("Project name")
        name_label.setStyleSheet("font-weight: 600;")
        name_label.setFixedWidth(110)
        name_row.addWidget(name_label)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Drop a video first…")
        self.name_input.setMinimumHeight(36)
        self.name_input.textChanged.connect(self._on_name_changed)
        name_row.addWidget(self.name_input, 1)
        v.addLayout(name_row)

        # Inline warning shown when a name collides
        self.name_warning = QLabel("")
        self.name_warning.setObjectName("TestResult")  # reuses red text style
        self.name_warning.setVisible(False)
        v.addWidget(self.name_warning)

        # Training mode toggle (Local / Cloud)
        mode_row = QHBoxLayout()
        mode_label = QLabel("Train")
        mode_label.setStyleSheet("font-weight: 600;")
        mode_row.addWidget(mode_label)
        mode_row.addSpacing(20)
        self.mode_group = QButtonGroup(self)
        self.local_radio = QRadioButton("On this computer")
        self.local_radio.setChecked(True)
        self.cloud_radio = QRadioButton("In the cloud")
        self.cloud_radio.setEnabled(False)  # _apply_cloud_state() may enable
        self.mode_group.addButton(self.local_radio)
        self.mode_group.addButton(self.cloud_radio)
        mode_row.addWidget(self.local_radio)
        mode_row.addSpacing(16)
        mode_row.addWidget(self.cloud_radio)
        mode_row.addStretch(1)
        v.addLayout(mode_row)

        # Flipping Cloud / Local should re-compute the time estimate next to
        # the Quality slider (cloud is ~10x faster than local).
        self.local_radio.toggled.connect(self._refresh_quality_label)
        self.cloud_radio.toggled.connect(self._refresh_quality_label)

        # Quality slider (training steps)
        q_row = QHBoxLayout()
        q_label = QLabel("Quality")
        q_label.setStyleSheet("font-weight: 600;")
        q_row.addWidget(q_label)
        q_row.addSpacing(20)
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(0, 2)   # 0=Fast, 1=Balanced, 2=High
        self.quality_slider.setValue(0)
        self.quality_slider.setFixedWidth(220)
        self.quality_slider.valueChanged.connect(self._update_quality_label)
        q_row.addWidget(self.quality_slider)
        q_row.addSpacing(12)
        self.quality_value = QLabel("Fast")
        self.quality_value.setStyleSheet("font-weight: 600;")
        q_row.addWidget(self.quality_value)
        # The actual text is filled in by _refresh_quality_label() once the
        # radio buttons exist; this default just keeps the layout from jumping
        # if it's read before the first signal fires.
        self.quality_eta = QLabel("")
        self.quality_eta.setObjectName("Hint")
        q_row.addSpacing(8)
        q_row.addWidget(self.quality_eta)
        q_row.addStretch(1)
        v.addLayout(q_row)

        # Train button + hint
        v.addStretch(1)
        self.train_hint = QLabel("Drop a video above to enable training")
        self.train_hint.setObjectName("Hint")
        self.train_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.train_hint)
        self.train_btn = QPushButton("Train splat")
        self.train_btn.setObjectName("Primary")
        self.train_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.train_btn.setEnabled(False)
        self.train_btn.clicked.connect(self._on_train)
        v.addWidget(self.train_btn)

        return page

    # ----- Run page -----

    def _build_run_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(16)

        head = QHBoxLayout()
        self.run_title = QLabel("Working…")
        self.run_title.setObjectName("H2")
        head.addWidget(self.run_title)
        head.addStretch(1)
        self.run_elapsed = QLabel("00:00")
        self.run_elapsed.setStyleSheet("font-size: 22px; font-weight: 700;")
        head.addWidget(self.run_elapsed)
        v.addLayout(head)

        self.run_sub = QLabel("Starting")
        self.run_sub.setObjectName("Status")
        v.addWidget(self.run_sub)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        v.addWidget(self.progress_bar)

        # Step list
        self.step_labels: dict[str, QLabel] = {}
        steps_box = QVBoxLayout()
        steps_box.setSpacing(8)
        for key, label in STAGES:
            row = QHBoxLayout()
            dot = QLabel("○")
            dot.setFixedWidth(18)
            text = QLabel(label)
            text.setObjectName("StepPending")
            row.addWidget(dot)
            row.addWidget(text)
            row.addStretch(1)
            steps_box.addLayout(row)
            self.step_labels[key] = text
            # Save the dot too for state changes
            self.step_labels[key + "__dot"] = dot
        v.addLayout(steps_box)

        v.addStretch(1)

        # Log box (collapsed by default — show toggle)
        self.log_box = QPlainTextEdit()
        self.log_box.setObjectName("Log")
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(180)
        self.log_box.setVisible(False)
        v.addWidget(self.log_box)
        self.log_toggle = QPushButton("Show detailed log")
        self.log_toggle.setObjectName("Subtle")
        self.log_toggle.clicked.connect(self._toggle_log)
        v.addWidget(self.log_toggle, alignment=Qt.AlignmentFlag.AlignLeft)

        # Cancel + Continue-in-background row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.background_btn = QPushButton("Continue in background")
        self.background_btn.setObjectName("Secondary")
        self.background_btn.setToolTip(
            "Hide this screen while training keeps running. You can keep "
            "browsing the app — we'll let you know when it's done."
        )
        self.background_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.background_btn.clicked.connect(self._on_continue_in_background)
        btn_row.addWidget(self.background_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("Secondary")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch(1)

        v.addLayout(btn_row)

        return page

    # ----- Done page -----

    def _build_done_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(20)

        title = QLabel("Splat ready")
        title.setObjectName("H1")
        v.addWidget(title)

        self.done_sub = QLabel("")
        self.done_sub.setObjectName("Lede")
        self.done_sub.setWordWrap(True)
        v.addWidget(self.done_sub)

        v.addSpacing(16)

        # Buttons row
        btn_row = QHBoxLayout()
        self.view_brush_btn = QPushButton("View Splat")
        self.view_brush_btn.setObjectName("Primary")
        self.view_brush_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_brush_btn.clicked.connect(self._on_view_in_brush)
        btn_row.addWidget(self.view_brush_btn)

        self.open_blender_btn = QPushButton("Open in Blender")
        self.open_blender_btn.setObjectName("Secondary")
        self.open_blender_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_blender_btn.clicked.connect(self._on_open_in_blender)
        btn_row.addWidget(self.open_blender_btn)

        self.open_folder_btn = QPushButton("Show files")
        self.open_folder_btn.setObjectName("Secondary")
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        btn_row.addWidget(self.open_folder_btn)

        btn_row.addStretch(1)
        v.addLayout(btn_row)

        # Train again — re-runs training (same video, possibly different quality)
        retrain_row = QHBoxLayout()
        retrain_row.addStretch(1)
        self.train_again_btn = QPushButton("Train Again")
        self.train_again_btn.setObjectName("Secondary")
        self.train_again_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.train_again_btn.clicked.connect(self._on_train_again)
        retrain_row.addWidget(self.train_again_btn)
        v.addLayout(retrain_row)

        v.addStretch(1)

        new_proj_btn = QPushButton("Start another")
        new_proj_btn.setObjectName("Subtle")
        new_proj_btn.clicked.connect(self._on_back)
        v.addWidget(new_proj_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        return page

    # ----- Public API -----

    def load_completed(self, project_dir: Path) -> None:
        """Open an existing project in its Done state.

        Used by ProjectsView when a user clicks a finished row.
        Populates state so View Splat / Open in Blender / Show files / Train Again
        all work against the right folder.
        """
        project_dir = Path(project_dir).resolve()
        self.output_dir = project_dir
        self._resuming_project_dir = project_dir

        # Read manifest to recover the original video path + quality, if present
        manifest = project_dir / "splatforge.json"
        original_video: Path | None = None
        quality: str = "fast"
        if manifest.exists():
            try:
                import json
                data = json.loads(manifest.read_text(encoding="utf-8"))
                src = data.get("source")
                if src:
                    p = Path(src)
                    if p.exists():
                        original_video = p
                q = data.get("quality")
                if q in ("fast", "balanced", "high"):
                    quality = q
            except Exception:
                pass
        self.video_path = original_video

        # Pre-fill the setup-page state so Train Again works smoothly
        self.name_input.setText(project_dir.name)
        self.quality_slider.setValue({"fast": 0, "balanced": 1, "high": 2}.get(quality, 0))
        if original_video:
            self.drop_label.setText(original_video.name)
            self.drop_zone.setObjectName("DropZoneActive")
        else:
            self.drop_label.setText("(original video missing — pick again to retrain)")
            self.drop_zone.setObjectName("DropZone")
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)
        self._refresh_train_enabled()
        self._apply_cloud_state()

        # Fill in the Done page text — always start with buttons enabled
        # in case a previous load_completed disabled them.
        self.view_brush_btn.setEnabled(True)
        self.open_blender_btn.setEnabled(True)
        ply = project_dir / "splat" / "scene.ply"
        if ply.exists():
            size_mb = ply.stat().st_size / 1024 / 1024
            self.done_sub.setText(
                f"{project_dir.name}\n"
                f"Trained at {quality.capitalize()} quality • "
                f"scene.ply = {size_mb:.1f} MB"
            )
        else:
            self.done_sub.setText(
                f"{project_dir.name}\n"
                f"Note: scene.ply not found — only Show files will work."
            )
            self.view_brush_btn.setEnabled(False)
            self.open_blender_btn.setEnabled(False)

        # Show the Done page
        self.stack.setCurrentIndex(2)

    def _on_train_again(self) -> None:
        """User clicked Train Again on the Done page — go back to setup with state pre-filled."""
        # Sanity: if we have no remembered video, force user to pick one
        if self.video_path is None or not self.video_path.exists():
            self.video_path = None
            self.drop_label.setText("Drop a video here or click to choose")
            self.drop_zone.setObjectName("DropZone")
            self.drop_zone.style().unpolish(self.drop_zone)
            self.drop_zone.style().polish(self.drop_zone)
            self.train_hint.setText("Drop the original video to retrain")
        self.name_warning.setVisible(False)
        self._refresh_train_enabled()
        # Note: _resuming_project_dir is kept set so collision-warning is skipped
        # for retraining into the same folder.
        self.stack.setCurrentIndex(0)

    def reset(self) -> None:
        """Reset the view back to a fresh setup page."""
        self.video_path = None
        self.output_dir = None
        self._resuming_project_dir = None
        self.drop_label.setText("Drop a video here or click to choose")
        self.drop_zone.setObjectName("DropZone")
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)
        self.train_btn.setEnabled(False)
        self.quality_slider.setValue(0)
        self.name_input.setText("")
        self.name_input.setPlaceholderText("Drop a video first…")
        self.name_warning.setVisible(False)
        self._apply_cloud_state()
        self.stack.setCurrentIndex(0)

    def _apply_cloud_state(self) -> None:
        """Enable/disable the Cloud radio based on whether an API key is saved."""
        connected = config.has_replicate_token()
        self.cloud_radio.setEnabled(connected)
        if connected:
            self.cloud_radio.setText("In the cloud")
            self.cloud_radio.setToolTip("")
        else:
            self.cloud_radio.setText("In the cloud (open Settings to enable)")
            self.cloud_radio.setToolTip("Paste your Replicate API key in Settings to enable cloud training.")
            # Force back to local if cloud was selected before key got removed
            if self.cloud_radio.isChecked():
                self.local_radio.setChecked(True)
        # Cloud-availability changed -> ETA hint may need to flip (cloud
        # disabled means we should always show the local time even if the
        # cloud radio still happens to be checked.)
        self._refresh_quality_label()

    # ----- Drag and drop -----

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and Path(urls[0].toLocalFile()).suffix.lower() in VIDEO_EXTS:
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if not urls:
            return
        path = Path(urls[0].toLocalFile())
        if path.suffix.lower() not in VIDEO_EXTS:
            return
        self._set_video(path)

    def _click_drop_zone(self, _event) -> None:
        # Only respond on the setup page
        if self.stack.currentIndex() != 0:
            return
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a video",
            "",
            "Videos (*.mp4 *.mov *.mkv *.avi *.m4v *.webm)",
        )
        if path_str:
            self._set_video(Path(path_str))

    def _set_video(self, path: Path) -> None:
        self.video_path = path
        self.drop_label.setText(path.name)
        self.drop_zone.setObjectName("DropZoneActive")
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)
        # Auto-populate the name from the video stem (sanitized) but only if
        # the user hasn't already typed something
        if not self.name_input.text().strip():
            self.name_input.setText(_sanitize_project_name(path.stem))
        self._refresh_train_enabled()

    # ----- Project name -----

    def _on_name_changed(self, _text: str) -> None:
        self.name_warning.setVisible(False)
        self._refresh_train_enabled()

    def _refresh_train_enabled(self) -> None:
        """Enable Train only when we have a video, a name, AND no other run alive."""
        has_video = self.video_path is not None
        has_name = bool(self.name_input.text().strip())
        # One-at-a-time guardrail: a background-running worker means we can't
        # start a second training. Train button stays disabled, hint explains.
        another_running = self.is_training()
        self.train_btn.setEnabled(has_video and has_name and not another_running)
        if another_running:
            self.train_hint.setText(
                "A training run is already in progress. Cancel it or wait for "
                "it to finish before starting another."
            )
        elif not has_video:
            self.train_hint.setText("Drop a video above to enable training")
        elif not has_name:
            self.train_hint.setText("Give your project a name")
        else:
            self.train_hint.setText("")

    # ----- Quality -----

    # Time estimates are based on real measured runs:
    #   Cloud (Replicate L40S) — fast=~40s, balanced=~2.5min, high=~6min
    #   Local (RTX 3060-class) — fast=~10min, balanced=~35min, high=~75min
    # Local times vary massively by GPU; cloud times are tight because the
    # hardware is fixed.
    _QUALITY_PRESETS = [
        # (name,       steps, cloud ETA,         local ETA)
        ("Fast",       5000,  "~1 min in cloud", "~10 min on a typical PC"),
        ("Balanced",   15000, "~3 min in cloud", "~35 min on a typical PC"),
        ("High",       30000, "~6 min in cloud", "~75+ min on a typical PC"),
    ]

    def _update_quality_label(self, value: int) -> None:
        name, _steps, _cloud_eta, _local_eta = self._QUALITY_PRESETS[value]
        self.quality_value.setText(name)
        self._refresh_quality_label()

    def _refresh_quality_label(self) -> None:
        """Recompute the ETA hint — depends on both the slider AND Cloud/Local radio."""
        value = self.quality_slider.value()
        _name, _steps, cloud_eta, local_eta = self._QUALITY_PRESETS[value]
        use_cloud = self.cloud_radio.isChecked() and self.cloud_radio.isEnabled()
        self.quality_eta.setText(cloud_eta if use_cloud else local_eta)

    def _selected_steps(self) -> int:
        return self._QUALITY_PRESETS[self.quality_slider.value()][1]

    def _selected_quality_preset(self) -> str:
        return ["fast", "balanced", "high"][self.quality_slider.value()]

    # ----- Train flow -----

    def _on_train(self) -> None:
        if self.video_path is None:
            return
        name = _sanitize_project_name(self.name_input.text())
        if not name:
            self.name_warning.setText("Project name can't be empty.")
            self.name_warning.setVisible(True)
            self.name_input.setFocus()
            return

        # Pick an output dir under the user's SplatfastK1 outputs folder
        project_root = config.get_outputs_dir() / name

        # If this is a re-train of the SAME project (user opened from Projects
        # list, set self._resuming_project_dir, and is now retraining) we
        # accept the collision. Otherwise warn.
        is_retrain_of_same = (
            self._resuming_project_dir is not None
            and project_root.resolve() == self._resuming_project_dir.resolve()
        )
        if project_root.exists() and not is_retrain_of_same:
            self.name_warning.setText(
                f"A project named \"{name}\" already exists. Pick a different name."
            )
            self.name_warning.setVisible(True)
            self.name_input.setFocus()
            self.name_input.selectAll()
            return

        self.name_warning.setVisible(False)
        self.stack.setCurrentIndex(1)  # run page
        self.run_title.setText("Working…")
        self.run_sub.setText("Starting")
        self.progress_bar.setValue(0)
        self.log_box.clear()
        for key, _label in STAGES:
            self.step_labels[key].setObjectName("StepPending")
            self.step_labels[key].style().unpolish(self.step_labels[key])
            self.step_labels[key].style().polish(self.step_labels[key])
            self.step_labels[key + "__dot"].setText("○")

        self.output_dir = project_root

        # Pick the right worker
        cloud_selected = self.cloud_radio.isChecked() and self.cloud_radio.isEnabled()
        if cloud_selected:
            self.worker = CloudPipelineWorker(
                video=self.video_path,
                output_dir=project_root,
                quality=self._selected_quality_preset(),
                total_steps=self._selected_steps(),
            )
        else:
            self.worker = PipelineWorker(
                video=self.video_path,
                output_dir=project_root,
                quality=self._selected_quality_preset(),
                total_steps=self._selected_steps(),
            )

        self.worker.stage_changed.connect(self._on_stage)
        self.worker.elapsed_changed.connect(self._on_elapsed)
        self.worker.log_line.connect(self._on_log)
        self.worker.finished_ok.connect(self._on_finished_ok)
        self.worker.finished_error.connect(self._on_finished_error)
        self.worker.start()

    def _on_cancel(self) -> None:
        # Write a sentinel marker BEFORE killing the subprocess. The Projects
        # view's scan reads this file to show "Stopped" instead of "In progress"
        # for cancelled runs — without it the log-modified-recently check would
        # mislabel a cancelled run as still active for up to 60 seconds.
        if self.output_dir is not None:
            try:
                marker = self.output_dir / ".cancelled"
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(
                    f"Cancelled by user at {__import__('time').strftime('%Y-%m-%d %H:%M:%S')}\n",
                    encoding="utf-8",
                )
            except Exception:
                pass
        if self.worker is not None:
            self.worker.cancel()
            self.worker = None
        self.stack.setCurrentIndex(0)

    def _on_continue_in_background(self) -> None:
        """User clicked 'Continue in background'. The worker thread keeps
        running. Just navigate the UI to Home and let them browse.
        """
        # Don't touch self.worker — it stays alive and keeps emitting signals.
        # When it finishes, _on_finished_ok / _on_finished_error will fire and
        # we'll detect whether the user is still here (visible) or off elsewhere.
        self.minimize_to_background.emit()

    # ----- Public helpers used by main window -----

    def is_training(self) -> bool:
        """True if a training worker is alive (running or about to start)."""
        return self.worker is not None and self.worker.isRunning()

    def active_project_dir(self):
        """Return the project dir of the currently-running training, or None."""
        if self.is_training():
            return self.output_dir
        return None

    def return_to_active_run(self) -> None:
        """Switch the project view's internal stack back to the run page so
        the user can see live logs again. Called by main window when they
        click the in-progress project in the Projects tab."""
        self.stack.setCurrentIndex(1)

    def _on_back(self) -> None:
        """Header "← Back" button — go home, but NEVER cancel a running worker.

        If you want to actually stop the training, use the Cancel button on the
        run page. Back is purely a navigation gesture; the training keeps going
        in the background, exactly like clicking "Continue in background".
        Old behavior cancelled the run, which surprised users who just wanted
        to glance at the Projects list.
        """
        self.back_to_start.emit()

    def _on_stage(self, stage_key: str, friendly: str, percent: int) -> None:
        self.run_sub.setText(friendly)
        self.progress_bar.setValue(percent)
        # Mark previous stages done, current active, rest pending
        keys = [k for k, _ in STAGES]
        if stage_key in keys:
            idx = keys.index(stage_key)
            for i, k in enumerate(keys):
                label = self.step_labels[k]
                dot = self.step_labels[k + "__dot"]
                if i < idx:
                    label.setObjectName("StepDone")
                    dot.setText("●")
                elif i == idx:
                    label.setObjectName("StepActive")
                    dot.setText("●")
                else:
                    label.setObjectName("StepPending")
                    dot.setText("○")
                label.style().unpolish(label)
                label.style().polish(label)

    def _on_elapsed(self, seconds: int) -> None:
        m, s = divmod(seconds, 60)
        self.run_elapsed.setText(f"{m:02d}:{s:02d}")

    def _on_log(self, line: str) -> None:
        self.log_box.appendPlainText(line)

    def _on_finished_ok(self, splat_ply: str) -> None:
        # Mark all stages done
        for k, _ in STAGES:
            label = self.step_labels[k]
            label.setObjectName("StepDone")
            label.style().unpolish(label)
            label.style().polish(label)
            self.step_labels[k + "__dot"].setText("●")
        self.progress_bar.setValue(100)

        self.done_sub.setText(
            f"Saved to {splat_ply}\nClick View Splat to see it in Brush, "
            "or Open in Blender to drop it into your scene."
        )
        # Always switch the internal stack to Done — if the user comes back
        # later (via Projects), they'll see the result waiting for them.
        self.stack.setCurrentIndex(2)
        # The worker is finished — clear it so the Home page's Train button
        # re-enables and the user can start a fresh project.
        was_visible = self.isVisible() and self.window().isActiveWindow()
        self.worker = None
        # If the user has navigated away (e.g. they hit "Continue in
        # background"), tell the main window so it can show a banner.
        if not was_visible:
            name = self.output_dir.name if self.output_dir else "Project"
            self.training_finished_in_background.emit(name, True)

    def _on_finished_error(self, message: str) -> None:
        # Stay on run page but flip title + sub to show the failure
        self.run_title.setText("Failed")
        self.run_sub.setText(message)
        was_visible = self.isVisible() and self.window().isActiveWindow()
        self.worker = None
        if not was_visible:
            name = self.output_dir.name if self.output_dir else "Project"
            self.training_finished_in_background.emit(name, False)

    # ----- Result buttons -----

    def _on_view_in_brush(self) -> None:
        if not self.output_dir:
            return
        from desktop.widgets.pipeline_worker import launch_brush_viewer
        launch_brush_viewer(self.output_dir / "splat" / "scene.ply")

    def _on_open_in_blender(self) -> None:
        if not self.output_dir:
            return
        from desktop.widgets.pipeline_worker import launch_blender_with_splat
        launch_blender_with_splat(self.output_dir / "splat" / "scene.ply")

    def _on_open_folder(self) -> None:
        if not self.output_dir:
            return
        import os
        os.startfile(str(self.output_dir))

    def _toggle_log(self) -> None:
        visible = not self.log_box.isVisible()
        self.log_box.setVisible(visible)
        self.log_toggle.setText("Hide detailed log" if visible else "Show detailed log")
