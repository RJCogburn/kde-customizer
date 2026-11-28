"""kdec-gui — theme editor with live preview. Thin layer over spec/build; no theme logic here."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtGui import QAction, QFont, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDockWidget, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu,
    QPlainTextEdit, QSplitter, QStackedWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from .. import spec, system
from .ai_panel import AIPanel
from .compare import CompareView
from .desktop_actions import DesktopActions
from .editing import Editing
from .fields import POPUPS, scroll
from .files import FileActions
from .icons_tab import IconsTab
from .pages.colors import ColorsPage
from .pages.desktop import DesktopPage
from .pages.fonts import FontsPage
from .pages.panels import PanelsPage
from .pages.theme import ThemePage
from .pages.tweaks import TweaksPage
from .preview import ensure_icon_paths, Preview
from .sections import Sections
from .start import StartPage


class Main(ThemePage, ColorsPage, DesktopPage, PanelsPage, FontsPage, TweaksPage, Editing, FileActions,
           DesktopActions, QMainWindow):
    """The editor window: start page or editor (sections + AI panel on the left, preview on the right), toolbar
    and output dock. The work is in the mixins: pages/* build the sections, editing.py keeps form, preview and
    undo in sync, files.py opens and saves, desktop_actions.py builds, applies and exports."""

    def __init__(self, path: str | None):
        super().__init__()
        self.path: Path | None = None
        self.theme = spec.Theme()
        self.dirty = False
        self._loading = False
        self._kept = False              # this window wrote the autosave (unsaved changes kept for recovery)
        self.installed = system.summary()

        self.preview = Preview()
        self.tabs = Sections()
        self.tabs.addTab(self._theme_tab(), "Theme", "documentinfo")
        self.tabs.addTab(self._colors_tab(), "Colors", "preferences-desktop-color")
        self.tabs.addTab(self._desktop_tab(), "Desktop", "preferences-desktop-theme-global")
        self.icons_tab = IconsTab(lambda: self.theme, lambda: self.path, self._ensure_saved)
        self.icons_tab.changed.connect(self.changed)
        self.icons_tab.icons_changed.connect(self._schedule_icons)
        self.icons_tab.generate.toggled.connect(lambda on: self.text["icons"].setEnabled(not on))
        self.tabs.addTab(scroll(self.icons_tab), "Icons", "preferences-desktop-icons")
        self.tabs.addTab(self._panels_tab(), "Panels", "preferences-desktop-plasma")
        self.tabs.addTab(self._fonts_tab(), "Fonts", "preferences-desktop-font")
        self.tabs.addTab(self._tweaks_tab(), "Tweaks", "configure")

        self.ai = AIPanel(lambda: self.from_form())
        self.ai.theme_ready.connect(self._ai_theme)
        self.ai.undo.clicked.connect(self.undo)
        self._undo_stack: list[spec.Theme] = []      # whole-theme snapshots; edits within ~0.6 s are one step
        self._redo_stack: list[spec.Theme] = []
        self._committed = copy.deepcopy(self.theme)

        # theme problems (kdec check), shown above the tabs while there are any
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setTextFormat(Qt.RichText)
        self.problems.setStyleSheet("QLabel { background: rgba(246, 180, 0, 0.16); border: 1px solid "
                                    "rgba(246, 180, 0, 0.55); border-radius: 5px; padding: 6px 8px; margin: 6px; }")
        self.problems.linkActivated.connect(lambda link: self.tabs.setCurrentIndex(int(link.split(":")[1])))
        self.problems.hide()

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        lv.addWidget(self.ai)
        line = QFrame(frameShape=QFrame.HLine, frameShadow=QFrame.Sunken)
        lv.addWidget(line)
        lv.addWidget(self.problems)
        from .finder import SettingFinder
        self.finder = SettingFinder(self.tabs, self._go_to_setting)
        fr = QHBoxLayout()
        fr.setContentsMargins(6, 6, 6, 2)
        fr.addWidget(self.finder)
        lv.addLayout(fr)
        lv.addWidget(self.tabs, 1)
        left.setMinimumWidth(440)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(6, 4, 0, 0)
        rv.setSpacing(2)
        bar = QHBoxLayout()
        self.popup = QComboBox()
        for label, key in POPUPS:
            self.popup.addItem(label, key)
        self.popup.setToolTip("Preview a popup or dialog (you can also click the launcher, clock or tray "
                              "in the preview's panel)")
        self.popup.currentIndexChanged.connect(lambda i: self.preview.set_popup(self.popup.itemData(i)))
        self.popup.currentIndexChanged.connect(lambda _i: self._update_compare())
        self.preview.popupChanged.connect(lambda key: self.popup.setCurrentIndex(max(0, self.popup.findData(key))))
        self.compare_btn = QToolButton(text="Compare with my desktop", icon=QIcon.fromTheme("view-split-left-right"),
                                       toolButtonStyle=Qt.ToolButtonTextBesideIcon, checkable=True)
        self.compare_btn.setToolTip("Your desktop as it is now next to this theme — drag the divider")
        self.compare_btn.toggled.connect(self.set_compare)
        bar.addWidget(self.compare_btn)
        bar.addStretch()
        from .. import vision
        self.vision = QComboBox()
        self.vision.addItem("Normal vision", "")
        for key, (label, _m) in vision.MODES.items():
            self.vision.addItem(label, key)
        self.vision.setToolTip("See the preview as people with color blindness do: colors that should differ "
                               "(accent, warnings, errors) must still look different")
        self.vision.currentIndexChanged.connect(lambda i: self.preview.set_vision(self.vision.itemData(i)))
        self.vision.currentIndexChanged.connect(lambda _i: self._update_compare())
        self.vision.setVisible(vision.available())
        bar.addWidget(self.vision)
        bar.addWidget(QLabel("Show:"))
        bar.addWidget(self.popup)
        rv.addLayout(bar)
        self.compare = CompareView()
        self.compare.resized.connect(self._update_compare)
        self._now_theme: spec.Theme | None = None
        self._now_preview: Preview | None = None
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self.preview)
        self.right_stack.addWidget(self.compare)
        rv.addWidget(self.right_stack, 1)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([500, 820])
        split.setChildrenCollapsible(False)
        self.start = StartPage()
        self.start.new_theme.connect(self.new)
        self.start.from_desktop.connect(self.from_desktop)
        self.start.from_image.connect(self.from_image)
        self.start.open_file.connect(self.open)
        self.start.open_path.connect(lambda p: self._open_path(Path(p)))
        self.start.open_starter.connect(lambda p: self.open_starter(Path(p)))
        self.start.manage.connect(self.manage_themes)
        self.start.recover.connect(self.recover)
        self.start.discard_recovery.connect(self.discard_recovery)
        self.start.setup_check.connect(self.setup_check)
        self.start.install_shared.connect(lambda: self.install_shared(None))
        self.setAcceptDrops(True)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.start)
        self.stack.addWidget(split)
        self.setCentralWidget(self.stack)

        self._toolbar()
        self._log_dock()
        self.setStatusBar(self.statusBar())

        # Coalesce rapid edits (typing, dragging in the color dialog) into one repaint.
        self._refresh = QTimer(self, singleShot=True, interval=60)
        self._refresh.timeout.connect(self._show_preview)
        # The generated icon set is rebuilt into a cache dir for the preview (debounced: ~0.2 s per build).
        self._icons_timer = QTimer(self, singleShot=True, interval=500)
        self._icons_timer.timeout.connect(self._build_preview_icons)
        self._icons_key = None
        self._commit_timer = QTimer(self, singleShot=True, interval=600)
        self._commit_timer.timeout.connect(self._commit)
        self._check_timer = QTimer(self, singleShot=True, interval=400)
        self._check_timer.timeout.connect(self._update_problems)

        self.to_form()
        QTimer.singleShot(1500, self._check_updates)
        if path:
            self.load(Path(path))
        if self.path:
            self.show_editor()
        else:
            self.show_start()
        self._update_title()

    def _toolbar(self) -> None:
        """The toolbar actions and their shortcuts (Ctrl+F focuses Find a setting)."""
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        def act(text, icon, fn, key=None, tip=None):
            a = QAction(QIcon.fromTheme(icon), text, self)
            a.triggered.connect(fn)
            if key:
                a.setShortcut(key)
            if tip:
                a.setToolTip(tip)
            tb.addAction(a)
            return a

        find = QAction(self)
        find.setShortcut(QKeySequence.Find)
        find.triggered.connect(lambda: (self.finder.setFocus(), self.finder.selectAll())
                               if self.stack.currentIndex() == 1 else None)
        self.addAction(find)
        self.home_act = act("Start", "go-home", self.show_start, None,
                            "Recent themes, starting points and installed themes")
        act("New", "document-new", self.new, QKeySequence.New)
        act("Open…", "document-open", self.open, QKeySequence.Open)
        act("From Desktop", "camera-photo", self.from_desktop, None,
            "Start a theme from your current desktop: colors, styles, fonts, panels and wallpaper")
        self.save_act = act("Save", "document-save", self.save, QKeySequence.Save,
            f"Saves into {system.themes_dir()}/<name>/ the first time")
        self.saveas_act = act("Save As…", "document-save-as", self.save_as, QKeySequence.SaveAs)
        tb.addSeparator()
        self.undo_act = act("Undo", "edit-undo", self.undo, QKeySequence.Undo, "Undo the last change (Ctrl+Z)")
        self.redo_act = act("Redo", "edit-redo", self.redo, QKeySequence.Redo, "Redo (Ctrl+Shift+Z)")
        for a in (self.undo_act, self.redo_act):
            tb.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonIconOnly)
        tb.addSeparator()
        self.build_act = act("Build", "run-build", self.do_build, "Ctrl+B", "Write theme files to build/")
        self.export_act = act("Export…", "document-export", self.export, "Ctrl+E",
                              "Pack a shareable .tar.gz with the wallpaper (the arrow: for the KDE Store)")
        menu = QMenu(self)
        menu.addAction(QIcon.fromTheme("document-export"), "Shareable archive (.tar.gz)…", self.export)
        menu.addAction(QIcon.fromTheme("get-hot-new-stuff"), "For the KDE Store…", self.export_store)
        self.export_act.setMenu(menu)
        tb.widgetForAction(self.export_act).setPopupMode(QToolButton.MenuButtonPopup)
        tb.addSeparator()
        self.with_layout = QCheckBox("Replace panels")
        self.with_layout.setToolTip("Also replace your current panels with the theme's panel layout")
        tb.addWidget(self.with_layout)
        apply = act("Apply to desktop", "dialog-ok-apply", self.apply, "Ctrl+Return",
                    "Build, install and apply to your live desktop (you get 20 seconds to keep or undo it)")
        self.apply_act = apply
        f = apply.font()
        f.setBold(True)
        apply.setFont(f)
        undo_apply = act("Undo Apply", "edit-undo", self.revert, None,
                         "Put the desktop back the way it was before the last Apply (every install takes a restore "
                         "point). The arrow lists earlier ones.")
        menu = QMenu(self)
        menu.addAction(QIcon.fromTheme("edit-undo"), "Undo the last Apply", self.revert)
        menu.addAction(QIcon.fromTheme("view-history"), "Earlier versions of my desktop…", self.history)
        undo_apply.setMenu(menu)
        tb.widgetForAction(undo_apply).setPopupMode(QToolButton.MenuButtonPopup)
        act("Installed…", "preferences-desktop-theme-global", self.manage_themes, None,
            "See and remove the themes kde-customizer has installed")
        self._editor_actions = [self.save_act, self.saveas_act, self.undo_act, self.redo_act, self.build_act,
                                self.export_act, self.apply_act, self.with_layout]

    def _log_dock(self) -> None:
        """The Output dock and the QProcess that runs scripts into it (Undo Apply)."""
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setFont(QFont("monospace"))
        self.dock = QDockWidget("Output", self)
        self.dock.setWidget(self.log)
        self.dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock)
        self.dock.hide()
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyRead.connect(lambda: self.say(bytes(self.proc.readAll()).decode(errors="replace").rstrip()))
        self._proc_done = None      # what to do when the running script ends: fn(exit code) -> status text
        self.proc.finished.connect(self._proc_finished)

    def _proc_finished(self, code: int, _status=None) -> None:
        done, self._proc_done = self._proc_done, None
        text = done(code) if done else ("Done." if code == 0 else f"failed (exit {code}) — see Output")
        self.statusBar().showMessage(text, 6000)

    def say(self, text: str) -> None:
        self.dock.show()
        self.log.appendPlainText(text)

    def show_start(self) -> None:
        self.start.refresh(recovery=not self._kept)     # our own unsaved changes are still open in the editor
        self.stack.setCurrentIndex(0)
        for a in self._editor_actions:
            a.setEnabled(False)
        self.home_act.setEnabled(False)
        self._update_undo()
        self._update_title()

    def show_editor(self) -> None:
        self.stack.setCurrentIndex(1)
        for a in self._editor_actions:
            a.setEnabled(True)
        self.home_act.setEnabled(True)
        self._update_undo()
        self._update_title()

    def _update_title(self) -> None:
        if self.stack.currentIndex() == 0:
            self.setWindowTitle("KDE Customizer")
            return
        name = self.path.name if self.path else "unsaved theme"
        self.setWindowTitle(f"{'• ' if self.dirty else ''}{name} — KDE Customizer")

    def closeEvent(self, e) -> None:
        """Ask about unsaved changes; wait for a running icon-preview build."""
        if self._confirm_discard():
            self._drop_autosave()
            if getattr(self, "_icons_thread", None):    # let a running icon-preview build finish
                self._icons_again = False
                self._icons_thread.quit()
                self._icons_thread.wait()
            e.accept()
        else:
            e.ignore()


def main() -> int:
    """kdec-gui entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName("KDE Customizer")
    app.setDesktopFileName("kde-customizer")  # matches kde-customizer.desktop
    ensure_icon_paths()
    app.setWindowIcon(QIcon.fromTheme("preferences-desktop-theme-global"))
    w = Main(sys.argv[1] if len(sys.argv) > 1 else None)
    w.resize(1320, 820)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
