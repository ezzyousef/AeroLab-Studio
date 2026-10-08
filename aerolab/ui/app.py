"""The main window: a navigation rail, the pages, a command palette and a status bar."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QMainWindow, QMessageBox, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import __version__
from .state import Session
from . import theme as T
from .pages import (AboutPage, CalculatorPage, DataPage, ExportPage, HomePage, MeasurePage,
                    PlotsPage, SettingsPage, ValidationPage)
from .widgets import CommandPalette, ToastHost, icon_label

__all__ = ["MainWindow", "run"]

PAGES = [
    ("home", HomePage, "Session"),
    ("data", DataPage, "Session"),
    ("calculator", CalculatorPage, "Analyse"),
    ("measure", MeasurePage, "Analyse"),
    ("plots", PlotsPage, "Analyse"),
    ("export", ExportPage, "Output"),
    ("validation", ValidationPage, "Output"),
    ("settings", SettingsPage, "Output"),
    ("about", AboutPage, "Output"),
]


class MainWindow(QMainWindow):
    def __init__(self, session: Session | None = None):
        super().__init__()
        self.session = session or Session()
        self.setWindowTitle("AeroLab Studio")
        # Small enough for a 1366x768 laptop at 125 % scaling; pages scroll below this.
        self.setMinimumSize(960, 600)
        self.resize(1440, 900)
        self.setWindowIcon(_app_icon())

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.rail = self._build_rail()
        layout.addWidget(self.rail)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)
        right_layout.addWidget(self._build_status_bar())
        layout.addWidget(right, 1)
        self.setCentralWidget(central)

        self.pages: dict[str, object] = {}
        for key, cls, _group in PAGES:
            page = cls(self.session)
            page.navigate.connect(self.go_to)
            self.pages[key] = page
            self.stack.addWidget(page)

        self.toasts = ToastHost(self)
        self.session.status.connect(self._on_status)
        self.session.busy.connect(self._on_busy)
        self.session.theme_changed.connect(self.apply_theme)
        self.session.runs_changed.connect(self._update_badges)
        self.session.datasets_changed.connect(self._update_badges)
        self.session.history_changed.connect(self._update_history_buttons)
        self.pages["data"].analysed.connect(lambda: self.go_to("measure"))
        self._update_history_buttons()

        self._build_menu()
        self._build_shortcuts()
        self.apply_theme(self.session.theme)
        self.go_to("home")

    # -- chrome --------------------------------------------------------------
    def _build_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("NavRail")
        rail.setFixedWidth(212)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(12, 16, 12, 14)
        layout.setSpacing(2)

        brand = QLabel("AeroLab Studio")
        brand.setObjectName("NavBrand")
        version = QLabel(f"v{__version__}")
        version.setObjectName("NavVersion")
        layout.addWidget(brand)
        layout.addWidget(version)
        layout.addSpacing(8)

        history = QHBoxLayout()
        history.setSpacing(6)
        self.btn_undo = QPushButton("↶  Undo")
        self.btn_undo.setObjectName("NavButton")
        self.btn_undo.setCursor(Qt.PointingHandCursor)
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo = QPushButton("↷  Redo")
        self.btn_redo.setObjectName("NavButton")
        self.btn_redo.setCursor(Qt.PointingHandCursor)
        self.btn_redo.clicked.connect(self.redo)
        history.addWidget(self.btn_undo)
        history.addWidget(self.btn_redo)
        layout.addLayout(history)
        layout.addSpacing(4)

        self.nav_buttons: dict[str, QPushButton] = {}
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        last_group = None
        for key, cls, group in PAGES:
            if group != last_group:
                label = QLabel(group.upper())
                label.setObjectName("NavSection")
                layout.addWidget(label)
                last_group = group
            btn = QPushButton(f"  {cls.glyph}   {cls.title}")
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, k=key: self.go_to(k))
            self.nav_group.addButton(btn)
            self.nav_buttons[key] = btn
            layout.addWidget(btn)

        layout.addStretch(1)
        hint = QLabel("Ctrl+K  ·  commands")
        hint.setObjectName("NavVersion")
        layout.addWidget(hint)
        return rail

    def _build_status_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(30)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(12)
        self.status_text = QLabel("Ready")
        self.status_text.setObjectName("StatusText")
        self.counts_text = QLabel("")
        self.counts_text.setObjectName("StatusText")
        layout.addWidget(self.status_text, 1)
        layout.addWidget(self.counts_text)
        return bar

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        for label, shortcut, slot in [
            ("&Import data…", QKeySequence.Open, lambda: self._page_action("data", "choose_files")),
            ("Load &demo datasets", "Ctrl+D", lambda: self._page_action("data", "load_samples")),
            (None, None, None),
            ("&Save session…", QKeySequence.Save, self.save_session),
            ("&Open session…", "Ctrl+Shift+O", self.open_session),
            (None, None, None),
            ("Export to &Excel…", "Ctrl+E", lambda: self._page_action("export", "export_excel")),
            ("Export to &Origin…", "Ctrl+R", lambda: self._page_action("export", "export_origin")),
            (None, None, None),
            ("E&xit", QKeySequence.Quit, self.close),
        ]:
            if label is None:
                file_menu.addSeparator()
                continue
            action = QAction(label, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(slot)
            file_menu.addAction(action)

        edit_menu = menu.addMenu("&Edit")
        self.action_undo = QAction("&Undo", self)
        self.action_undo.setShortcut(QKeySequence.Undo)
        self.action_undo.triggered.connect(self.undo)
        self.action_redo = QAction("&Redo", self)
        self.action_redo.setShortcut(QKeySequence.Redo)
        self.action_redo.triggered.connect(self.redo)
        edit_menu.addAction(self.action_undo)
        edit_menu.addAction(self.action_redo)

        view_menu = menu.addMenu("&View")
        for key, cls, _group in PAGES:
            action = QAction(cls.title, self)
            action.triggered.connect(lambda _c=False, k=key: self.go_to(k))
            view_menu.addAction(action)
        view_menu.addSeparator()
        toggle = QAction("Toggle &theme", self)
        toggle.setShortcut("Ctrl+T")
        toggle.triggered.connect(self.toggle_theme)
        view_menu.addAction(toggle)

        help_menu = menu.addMenu("&Help")
        about = QAction("&About AeroLab Studio", self)
        about.triggered.connect(lambda: self.go_to("about"))
        help_menu.addAction(about)
        guide = QAction("&User guide", self)
        guide.triggered.connect(self.open_guide)
        help_menu.addAction(guide)

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+K"), self, self.show_palette)
        QShortcut(QKeySequence("Ctrl+P"), self, self.show_palette)
        QShortcut(QKeySequence.Undo, self, self.undo)
        QShortcut(QKeySequence.Redo, self, self.redo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self.redo)
        for i, (key, _cls, _g) in enumerate(PAGES[:9], start=1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, lambda k=key: self.go_to(k))

    # -- navigation ----------------------------------------------------------
    def go_to(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        button = self.nav_buttons.get(key)
        if button is not None:
            button.setChecked(True)
        page.refresh()

    # -- history -------------------------------------------------------------
    def undo(self) -> None:
        self.session.undo()

    def redo(self) -> None:
        self.session.redo()

    def _update_history_buttons(self) -> None:
        can_undo, can_redo = self.session.can_undo(), self.session.can_redo()
        self.btn_undo.setEnabled(can_undo)
        self.btn_redo.setEnabled(can_redo)
        self.btn_undo.setToolTip(f"Undo {self.session.undo_label()}   (Ctrl+Z)"
                                 if can_undo else "Nothing to undo")
        self.btn_redo.setToolTip(f"Redo {self.session.redo_label()}   (Ctrl+Y)"
                                 if can_redo else "Nothing to redo")
        for action, enabled, label, verb in (
                (getattr(self, "action_undo", None), can_undo, self.session.undo_label(), "Undo"),
                (getattr(self, "action_redo", None), can_redo, self.session.redo_label(), "Redo")):
            if action is not None:
                action.setEnabled(enabled)
                action.setText(f"&{verb} {label}" if enabled else f"&{verb}")

    def _page_action(self, page_key: str, method: str) -> None:
        self.go_to(page_key)
        page = self.pages.get(page_key)
        fn = getattr(page, method, None)
        if callable(fn):
            QTimer.singleShot(0, fn)

    # -- theme ---------------------------------------------------------------
    def apply_theme(self, theme: str) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(T.stylesheet(theme))
        for page in self.pages.values():
            page.on_theme_changed(theme)

    def toggle_theme(self) -> None:
        self.session.set_setting("theme", "dark" if self.session.theme == "light" else "light")

    # -- session -------------------------------------------------------------
    def save_session(self) -> None:
        start = self.session.settings.get("last_export_dir", str(Path.home()))
        name = self.session.project_name.replace(" ", "_")
        path, _f = QFileDialog.getSaveFileName(self, "Save session", f"{start}/{name}.aerolab",
                                               "AeroLab session (*.aerolab)")
        if not path:
            return
        try:
            self.session.save_project(path)
        except Exception as exc:                                # noqa: BLE001
            self.session.status.emit(f"Could not save the session: {exc}", "error")

    def open_session(self) -> None:
        start = self.session.settings.get("last_export_dir", str(Path.home()))
        path, _f = QFileDialog.getOpenFileName(self, "Open session", start,
                                               "AeroLab session (*.aerolab);;All files (*)")
        if not path:
            return
        try:
            self.session.load_project(path)
            self.go_to("measure")
        except Exception as exc:                                # noqa: BLE001
            self.session.status.emit(f"Could not open that session: {exc}", "error")

    # -- palette -------------------------------------------------------------
    def show_palette(self) -> None:
        commands: list[tuple[str, str, object]] = []
        for key, cls, group in PAGES:
            commands.append((f"Go to {cls.title}", group, lambda k=key: self.go_to(k)))
        commands += [
            ("Import data files", "File", lambda: self._page_action("data", "choose_files")),
            ("Load demo datasets", "File", lambda: self._page_action("data", "load_samples")),
            ("Analyse all imported datasets", "Analyse",
             lambda: self._page_action("data", "analyse_all")),
            ("Save session", "File", self.save_session),
            ("Open session", "File", self.open_session),
            ("Export to Excel", "Output", lambda: self._page_action("export", "export_excel")),
            ("Export to Origin", "Output", lambda: self._page_action("export", "export_origin")),
            ("Write LabTalk package", "Output",
             lambda: self._page_action("export", "export_origin")),
            ("Export figure set", "Output", lambda: self._page_action("export", "export_images")),
            ("Re-run validation", "Output", lambda: self._page_action("validation", "refresh")),
            ("Undo last action", "Edit", self.undo),
            ("Redo", "Edit", self.redo),
            ("Toggle light / dark theme", "View", self.toggle_theme),
            ("Clear all runs", "Session", self.session.clear_runs),
            ("Clear imported datasets", "Session", self.session.clear_datasets),
            ("About AeroLab Studio", "Help", self.show_about),
        ]
        palette = CommandPalette(commands, self)
        palette.show_centred()

    # -- feedback ------------------------------------------------------------
    def _on_status(self, message: str, level: str) -> None:
        self.status_text.setText(message)
        self.toasts.show_message(message, level)

    def _on_busy(self, busy: bool, message: str) -> None:
        if busy and message:
            self.status_text.setText(message)
        self.setCursor(Qt.BusyCursor if busy else Qt.ArrowCursor)

    def _update_badges(self) -> None:
        counts = self.session.counts()
        self.counts_text.setText(
            f"{counts['datasets']} dataset(s)  ·  {counts['runs']} run(s)  ·  "
            f"{counts['metrics']} result(s)")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "toasts"):
            self.toasts._reposition()

    # -- help ----------------------------------------------------------------
    def show_about(self) -> None:
        from ..core import equations as E, measurements as M
        QMessageBox.about(
            self, "About AeroLab Studio",
            f"<h3>AeroLab Studio {__version__}</h3>"
            "<p>Equations, measurements and publication figures for aerogel-fibre research.</p>"
            f"<p>{len(E.REGISTRY)} equations · {len(M.MEASUREMENTS)} measurements · "
            "OriginLab and Excel export.</p>"
            "<p>Built from Omranpour <i>et al.</i> (2024a, 2024b, 2025).</p>")

    def open_guide(self) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        guide = Path(__file__).resolve().parents[2] / "docs" / "USER_GUIDE.md"
        if guide.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(guide)))
        else:
            self.session.status.emit(f"User guide not found at {guide}", "warning")

    def closeEvent(self, event) -> None:  # noqa: N802
        export = self.pages.get("export")
        if export is not None and export.is_busy():
            answer = QMessageBox.question(
                self, "Export in progress",
                "An Origin export is still running.\n\n"
                "Wait for it to finish before closing?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                event.ignore()
                return
        if export is not None:
            # The Origin thread outlives single exports, so it is joined on every close --
            # Qt aborts the process when a running QThread is destroyed.
            export.wait_for_export()
        self.session.save_settings()
        super().closeEvent(event)


def icon_path() -> Path | None:
    """The bundled .ico, whether running from source or from a frozen build."""
    roots = [Path(__file__).resolve().parents[2]]
    if getattr(sys, "frozen", False):
        roots.insert(0, Path(getattr(sys, "_MEIPASS", ".")))
        roots.insert(1, Path(sys.executable).parent)
    for root in roots:
        for candidate in (root / "build_assets" / "aerolab.ico", root / "aerolab.ico"):
            if candidate.is_file():
                return candidate
    return None


def app_pixmap(size: int = 64) -> QPixmap:
    """The application mark at any size: the real .ico when present, else drawn."""
    path = icon_path()
    if path is not None:
        pixmap = QIcon(str(path)).pixmap(size, size)
        if not pixmap.isNull():
            return pixmap

    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QPainter, QPen

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    s = size / 64.0
    painter.setBrush(QColor("#0072B2"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(int(2 * s), int(2 * s), int(60 * s), int(60 * s), 14 * s, 14 * s)
    painter.setPen(QPen(QColor("#FFFFFF"), max(1.5, 5 * s), Qt.SolidLine,
                        Qt.RoundCap, Qt.RoundJoin))
    painter.drawPolyline([                       # a small rising curve
        QPoint(int(14 * s), int(46 * s)), QPoint(int(26 * s), int(34 * s)),
        QPoint(int(38 * s), int(38 * s)), QPoint(int(50 * s), int(18 * s)),
    ])
    painter.end()
    return pixmap


def _app_icon() -> QIcon:
    """The window and taskbar icon, with every size Windows asks for."""
    path = icon_path()
    if path is not None:
        icon = QIcon(str(path))
        if not icon.isNull():
            return icon
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_pixmap(size))
    return icon


def _claim_taskbar_identity() -> None:
    """Tell Windows this is its own application, not a Python host.

    Without an explicit AppUserModelID the shell groups the window under python.exe and
    shows the Python icon in the taskbar, whatever icon the window itself carries.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "AeroLab.Studio.Desktop.1")
    except Exception:                                # noqa: BLE001 - cosmetic only
        pass


def run(argv: list[str] | None = None) -> int:
    """Start the application."""
    argv = list(argv if argv is not None else sys.argv)
    _claim_taskbar_identity()
    QApplication.setAttribute(Qt.AA_DontUseNativeMenuBar, False)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("AeroLab Studio")
    app.setApplicationDisplayName("AeroLab Studio")
    app.setOrganizationName("AeroLab")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(_app_icon())               # the taskbar reads this one

    window = MainWindow()
    window.show()

    # Files passed on the command line are imported once the window is up.
    files = [a for a in argv[1:] if not a.startswith("-") and Path(a).exists()]
    if files:
        sessions = [f for f in files if f.lower().endswith(".aerolab")]
        data_files = [f for f in files if f not in sessions]
        QTimer.singleShot(120, lambda: _open_startup_files(window, sessions, data_files))
    return app.exec()


def _open_startup_files(window: MainWindow, sessions: list[str], data_files: list[str]) -> None:
    """Handle whatever was double-clicked or passed on the command line."""
    for path in sessions[:1]:                 # a session replaces the state, so take one
        try:
            window.session.load_project(path)
            window.go_to("measure")
        except Exception as exc:              # noqa: BLE001 - reported in the UI
            window.session.status.emit(f"Could not open {Path(path).name}: {exc}", "error")
    if data_files:
        window.go_to("data")
        window.pages["data"].import_paths(data_files)
