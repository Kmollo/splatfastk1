"""SplatfastK1 — main window shell.

Layout: [ Sidebar (220 px) | Stacked content area ].
Sidebar swaps content between Home (start screen), Settings, Projects, and
the Project View (active project flow).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QMainWindow,
    QStackedWidget,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QFrame,
    QLabel,
    QPushButton,
)

from desktop import setup_helpers as sh
from desktop.widgets.sidebar import Sidebar, PAGE_HOME, PAGE_SETTINGS, PAGE_PROJECTS
from desktop.widgets.start_screen import StartScreen
from desktop.widgets.project_view import ProjectView
from desktop.widgets.settings_view import SettingsView
from desktop.widgets.projects_view import ProjectsView
from desktop.widgets.setup_view import SetupView


# Stack indices
IDX_HOME = 0
IDX_SETTINGS = 1
IDX_PROJECTS = 2
IDX_ACTIVE_PROJECT = 3
IDX_SETUP = 4


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SplatfastK1")
        self.resize(1100, 760)
        self.setMinimumSize(900, 600)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left sidebar
        self.sidebar = Sidebar()
        root.addWidget(self.sidebar)

        # Vertical divider — black line between sidebar and main content
        divider = QFrame()
        divider.setObjectName("VDivider")
        divider.setFixedWidth(2)
        root.addWidget(divider)

        # Right side: banner (hidden by default) + content stack vertically
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        # In-app banner for "training finished in background" notifications.
        # Hidden until something completes while the user is on another page.
        self.banner = QFrame()
        self.banner.setObjectName("Banner")
        self.banner.setVisible(False)
        b_lay = QHBoxLayout(self.banner)
        b_lay.setContentsMargins(16, 10, 16, 10)
        b_lay.setSpacing(12)
        self.banner_label = QLabel("")
        self.banner_label.setObjectName("BannerText")
        b_lay.addWidget(self.banner_label, 1)
        self.banner_view_btn = QPushButton("View")
        self.banner_view_btn.setObjectName("BannerView")
        self.banner_view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.banner_view_btn.clicked.connect(self._banner_view_clicked)
        b_lay.addWidget(self.banner_view_btn)
        self.banner_dismiss_btn = QPushButton("X")
        self.banner_dismiss_btn.setObjectName("BannerDismiss")
        self.banner_dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.banner_dismiss_btn.setFixedWidth(28)
        self.banner_dismiss_btn.clicked.connect(self._dismiss_banner)
        b_lay.addWidget(self.banner_dismiss_btn)
        right_lay.addWidget(self.banner)

        # Auto-dismiss banner after 30s
        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.timeout.connect(self._dismiss_banner)

        # Content stack
        self.stack = QStackedWidget()
        right_lay.addWidget(self.stack, 1)
        root.addWidget(right, 1)

        # Pages
        self.start_screen = StartScreen()
        self.settings_view = SettingsView()
        self.projects_view = ProjectsView()
        self.project_view = ProjectView()
        self.setup_view = SetupView()

        # Track which page the user came from when entering the project view.
        # Used by _back_to_start so the Back button returns them to where they
        # were instead of always defaulting to Home.
        self._project_came_from: str = PAGE_HOME

        self.stack.addWidget(self.start_screen)     # IDX_HOME
        self.stack.addWidget(self.settings_view)    # IDX_SETTINGS
        self.stack.addWidget(self.projects_view)    # IDX_PROJECTS
        self.stack.addWidget(self.project_view)     # IDX_ACTIVE_PROJECT
        self.stack.addWidget(self.setup_view)       # IDX_SETUP

        # Wire signals
        self.sidebar.nav.connect(self._on_nav)
        self.start_screen.start_clicked.connect(self._open_new_project)
        self.project_view.back_to_start.connect(self._back_to_start)
        self.project_view.minimize_to_background.connect(self._on_minimize_to_background)
        self.project_view.training_finished_in_background.connect(self._on_training_finished_in_background)
        self.projects_view.open_project.connect(self._open_existing_project)
        self.setup_view.continue_to_home.connect(self._setup_done)

        # First-launch routing: if required deps missing, show Setup first.
        # Otherwise go straight to Home. Settings → "Re-run setup" can re-show
        # the Setup page at any time via show_setup().
        if sh.all_required_ok():
            self.stack.setCurrentIndex(IDX_HOME)
            self.sidebar.set_active(PAGE_HOME)
        else:
            self.show_setup()

    # ----- Navigation -----

    def _on_nav(self, page_key: str) -> None:
        if page_key == PAGE_HOME:
            self.stack.setCurrentIndex(IDX_HOME)
        elif page_key == PAGE_SETTINGS:
            self.settings_view.refresh_from_storage()
            self.stack.setCurrentIndex(IDX_SETTINGS)
        elif page_key == PAGE_PROJECTS:
            self.projects_view.refresh()
            self.stack.setCurrentIndex(IDX_PROJECTS)

    def _open_new_project(self) -> None:
        # Don't blow away an in-progress training. If something is running
        # in the background, route the user back to it instead of resetting.
        if self.project_view.is_training():
            self.project_view.return_to_active_run()
            self.stack.setCurrentIndex(IDX_ACTIVE_PROJECT)
            self.sidebar.set_active("")
            return
        # Remember they came from Home so Back returns them here, not Projects.
        self._project_came_from = PAGE_HOME
        self.project_view.reset()
        self.stack.setCurrentIndex(IDX_ACTIVE_PROJECT)
        # Keep sidebar showing nothing-selected since active-project is unlisted
        self.sidebar.set_active("")

    def _back_to_start(self) -> None:
        """Project view's "← Back" handler — route to wherever the user
        entered the project from (Home if they clicked 'Start a new project',
        Projects if they clicked a row in the Projects list).
        """
        if self._project_came_from == PAGE_PROJECTS:
            self.projects_view.refresh()
            self.stack.setCurrentIndex(IDX_PROJECTS)
            self.sidebar.set_active(PAGE_PROJECTS)
        else:
            self.stack.setCurrentIndex(IDX_HOME)
            self.sidebar.set_active(PAGE_HOME)

    def _on_minimize_to_background(self) -> None:
        """User clicked 'Continue in background'. Worker keeps running.
        Navigate to Home so they can browse while it trains.
        """
        self.stack.setCurrentIndex(IDX_HOME)
        self.sidebar.set_active(PAGE_HOME)

    def _open_existing_project(self, project_dir: Path) -> None:
        """Click on a Projects list row.

        Smart routing:
          * If this is the CURRENTLY-RUNNING project → jump to the live run
            page so they see the in-progress log.
          * Otherwise → load it into the Done page like before.
        """
        active = self.project_view.active_project_dir()
        if active is not None and active.resolve() == project_dir.resolve():
            self.project_view.return_to_active_run()
            self.stack.setCurrentIndex(IDX_ACTIVE_PROJECT)
            self.sidebar.set_active("")
            return
        # User clicked a row in the Projects list — remember that so Back
        # returns them to Projects, not Home.
        self._project_came_from = PAGE_PROJECTS
        self.project_view.load_completed(project_dir)
        self.stack.setCurrentIndex(IDX_ACTIVE_PROJECT)
        # No sidebar item selected — active project is not a nav destination
        self.sidebar.set_active("")

    # ----- In-app notification banner -----

    def _on_training_finished_in_background(self, project_name: str, success: bool) -> None:
        """A worker finished while the user was browsing elsewhere. Show a
        non-intrusive banner above the main content."""
        if success:
            self.banner_label.setText(f"✓ {project_name} training finished.")
        else:
            self.banner_label.setText(f"⚠ {project_name} training failed. Click View for details.")
        self.banner.setVisible(True)
        self._banner_project_dir = self.project_view.output_dir
        self._banner_timer.start(30000)  # 30s auto-dismiss

    def _banner_view_clicked(self) -> None:
        self._dismiss_banner()
        # Route back to the project view (which is already on the Done /
        # Failure page internally — _on_finished_ok / _on_finished_error
        # took care of that).
        self.stack.setCurrentIndex(IDX_ACTIVE_PROJECT)
        self.sidebar.set_active("")

    def _dismiss_banner(self) -> None:
        self.banner.setVisible(False)
        self._banner_timer.stop()

    # ----- First-launch setup -----

    def show_setup(self) -> None:
        """Switch to the Setup page. Disables sidebar nav so the user can't
        wander off mid-install. Called on first launch (auto) or from
        Settings → Re-run setup (manual)."""
        self.setup_view.refresh()
        self.stack.setCurrentIndex(IDX_SETUP)
        self.sidebar.set_active("")
        self.sidebar.setEnabled(False)

    def _setup_done(self) -> None:
        """User clicked 'Continue to Home' on the Setup page."""
        self.sidebar.setEnabled(True)
        self.stack.setCurrentIndex(IDX_HOME)
        self.sidebar.set_active(PAGE_HOME)
