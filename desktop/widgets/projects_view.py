"""SplatfastK1 — Projects page.

Lists past projects found in the outputs folder. Click a row to reopen.
Right-click for delete.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QMenu,
)

from desktop import config


class _ProjectRow(QFrame):
    """One row in the projects list. Clickable. Right-click = delete menu."""

    clicked = pyqtSignal(Path)
    request_delete = pyqtSignal(Path)
    request_open_folder = pyqtSignal(Path)

    def __init__(self, project_dir: Path, status: str, modified: datetime) -> None:
        super().__init__()
        self.project_dir = project_dir
        self.setObjectName("ProjectRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context)

        h = QHBoxLayout(self)
        h.setContentsMargins(16, 12, 16, 12)

        icon = QLabel("📁")
        icon.setStyleSheet("font-size: 18px;")
        h.addWidget(icon)

        info = QVBoxLayout()
        info.setSpacing(2)
        name = QLabel(project_dir.name)
        name.setStyleSheet("font-weight: 600; font-size: 14px;")
        info.addWidget(name)
        when = QLabel(modified.strftime("%a %b %d, %I:%M %p"))
        when.setObjectName("Hint")
        info.addWidget(when)
        h.addLayout(info, 1)

        # Status badge
        badge = QLabel(status)
        if status.lower().startswith("done"):
            badge.setObjectName("BadgeOk")
        elif status.lower().startswith("fail"):
            badge.setObjectName("BadgeBad")
        else:
            badge.setObjectName("BadgeMuted")
        h.addWidget(badge)

    def mousePressEvent(self, event):  # noqa: N802 — Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.project_dir)
        super().mousePressEvent(event)

    def _on_context(self, pos) -> None:
        menu = QMenu(self)
        act_open = menu.addAction("Open folder")
        act_delete = menu.addAction("Delete")
        action = menu.exec(self.mapToGlobal(pos))
        if action == act_open:
            self.request_open_folder.emit(self.project_dir)
        elif action == act_delete:
            self.request_delete.emit(self.project_dir)


class ProjectsView(QWidget):
    """Lists past projects from the outputs folder."""

    open_project = pyqtSignal(Path)   # main window listens to reopen in ProjectView

    def __init__(self) -> None:
        super().__init__()

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(20)

        # Header
        header = QHBoxLayout()
        title = QLabel("Projects")
        title.setObjectName("H1")
        header.addWidget(title)
        header.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("Secondary")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        root.addLayout(header)

        # Scroll area with list
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.scroll, 1)

        # Empty state placeholder
        self._empty = QLabel(
            "No projects yet.\nClick \"Start a new project\" on the home page to make your first one."
        )
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setObjectName("Lede")
        self._empty.setWordWrap(True)

        self.refresh()

    # ----- Public -----

    def refresh(self) -> None:
        """Re-scan outputs folder and rebuild the list."""
        out_dir = config.get_outputs_dir()
        rows = self._scan(out_dir)

        container = QWidget()
        v = QVBoxLayout(container)
        v.setSpacing(8)
        v.setContentsMargins(0, 0, 0, 0)

        if not rows:
            v.addStretch(1)
            v.addWidget(self._empty)
            v.addStretch(1)
        else:
            for project_dir, status, mtime in rows:
                row = _ProjectRow(project_dir, status, mtime)
                row.clicked.connect(self._on_row_clicked)
                row.request_delete.connect(self._on_row_delete)
                row.request_open_folder.connect(self._on_row_open_folder)
                v.addWidget(row)
            v.addStretch(1)

        self.scroll.setWidget(container)

    # ----- Scanning -----

    def _scan(self, out_dir: Path) -> list[tuple[Path, str, datetime]]:
        """Find project folders. Returns (path, status, modified_time) sorted newest first.

        Status rules — be honest about what each label means:
          * Done      → splat/scene.ply exists and is non-trivially sized
          * Failed    → pipeline.log explicitly logged a failure (or it ran
                        to "complete" but produced no .ply, meaning post-CLI
                        cloud upload / training crashed)
          * Stopped   → log exists but pipeline never reached a PIPELINE_END
                        marker AND hasn't been written to in >60 seconds.
                        This is the "you clicked Cancel" or "app crashed"
                        state. The old code mislabelled this as "In progress".
          * In progress → genuinely active: log was written to within the
                        last 60 seconds AND no PIPELINE_END marker yet.
        """
        import time as _time
        if not out_dir.exists():
            return []
        results: list[tuple[Path, str, datetime]] = []
        for child in out_dir.iterdir():
            if not child.is_dir():
                continue
            ply = child / "splat" / "scene.ply"
            log_file = child / "logs" / "pipeline.log"
            cancelled_marker = child / ".cancelled"
            cloud_active_marker = child / ".cloud_active"

            status: str
            if ply.exists() and ply.stat().st_size > 1024:
                status = "Done"
            elif cancelled_marker.exists():
                # User explicitly cancelled this run. Don't let the "log was
                # recently modified" path mislabel it as still running.
                status = "Stopped"
            elif cloud_active_marker.exists():
                # Cloud worker is in upload / poll / download phase. The
                # local pipeline.log already says "PIPELINE_END: complete"
                # at this point because the local CLI ran with --backend=none
                # and finished after COLMAP. Without this check we'd mislabel
                # active cloud training as Failed.
                status = "In progress"
            elif log_file.exists():
                try:
                    log_text = log_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    log_text = ""
                log_age_s = _time.time() - log_file.stat().st_mtime
                if "PIPELINE_END: failed" in log_text:
                    status = "Failed"
                elif "PIPELINE_END: complete" in log_text:
                    # CLI finished, but no .ply → either cloud step never wrote
                    # one (cancel / crash) or local backend failed silently.
                    status = "Failed"
                elif log_age_s < 60:
                    status = "In progress"
                else:
                    status = "Stopped"
            elif any(child.iterdir()):
                # Folder has SOMETHING but no log — probably a half-created
                # project that never even started. Show it anyway so the user
                # can delete it.
                status = "Stopped"
            else:
                continue

            mtime = datetime.fromtimestamp(child.stat().st_mtime)
            results.append((child, status, mtime))
        results.sort(key=lambda t: t[2], reverse=True)
        return results

    # ----- Row handlers -----

    def _on_row_clicked(self, project_dir: Path) -> None:
        self.open_project.emit(project_dir)

    def _on_row_open_folder(self, project_dir: Path) -> None:
        try:
            os.startfile(str(project_dir))
        except Exception:
            pass

    def _on_row_delete(self, project_dir: Path) -> None:
        # Send to Recycle Bin if possible (safer), else hard delete
        try:
            from send2trash import send2trash  # optional best-effort
            send2trash(str(project_dir))
        except ImportError:
            shutil.rmtree(project_dir, ignore_errors=True)
        self.refresh()
