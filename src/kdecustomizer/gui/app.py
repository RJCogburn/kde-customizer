"""kdec-gui — theme editor with live preview. Thin layer over spec/build; no theme logic here."""
from __future__ import annotations

import copy
import html
import re
import sys
from dataclasses import fields
from pathlib import Path

from PySide6.QtCore import QProcess, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox, QDockWidget, QFileDialog,
    QFontDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QHeaderView, QInputDialog, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget, QTabWidget,
    QTableWidget, QTableWidgetItem, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from .. import build as builder
from .. import ai, color, library, spec, system
from .. import cursorset, iconset
from .ai_panel import AIPanel
from .apply_dialog import ApplyDialog
from .manager import ThemeManager
from .start import StartPage
from .icons_tab import IconsTab
from .preview import Preview, ensure_icon_paths

COMMON_WIDGETS = [
    "org.kde.plasma.kickoff", "org.kde.plasma.icontasks", "org.kde.plasma.taskmanager",
    "org.kde.plasma.pager", "org.kde.plasma.marginsseparator", "org.kde.plasma.panelspacer",
    "org.kde.plasma.systemtray", "org.kde.plasma.digitalclock", "org.kde.plasma.showdesktop",
]


# --- small field widgets ------------------------------------------------------------

class ColorField(QWidget):
    """Swatch button + editable hex."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.swatch = QPushButton()
        self.swatch.setFixedSize(44, 26)
        self.swatch.setCursor(Qt.PointingHandCursor)
        self.swatch.clicked.connect(self._pick)
        self.hex = QLineEdit()
        self.hex.setMaxLength(7)
        self.hex.setFixedWidth(90)
        self.hex.setFont(QFont("monospace"))
        self.hex.textEdited.connect(self._typed)
        lay.addWidget(self.swatch)
        lay.addWidget(self.hex)
        lay.addStretch()

    @property
    def value(self) -> str:
        return self.hex.text().strip()

    def set(self, value: str) -> None:
        self.hex.setText(value)
        self._paint(value)

    def _paint(self, value: str) -> None:
        ok = QColor(value).isValid() and len(value) in (4, 7)
        self.swatch.setStyleSheet(
            f"background:{value}; border:1px solid palette(mid); border-radius:5px;" if ok
            else "border:1px dashed palette(mid); border-radius:5px;")

    def _typed(self, text: str) -> None:
        if not text.startswith("#"):
            self.hex.setText("#" + text)
        self._paint(self.value)
        try:
            color.parse(self.value)
        except ValueError:
            return
        self.changed.emit()

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self.value), self)
        if c.isValid():
            self.set(c.name())
            self.changed.emit()


class FontField(QWidget):
    """'Family,size' text with a font picker; empty = leave the user's font alone."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(placeholderText="unchanged")
        self.edit.textChanged.connect(self.changed)
        pick = QPushButton("Choose…")
        pick.clicked.connect(self._pick)
        clear = QPushButton(icon=QIcon.fromTheme("edit-clear"))
        clear.setToolTip("Leave unchanged")
        clear.clicked.connect(lambda: self.edit.setText(""))
        lay.addWidget(self.edit, 1)
        lay.addWidget(pick)
        lay.addWidget(clear)

    def _pick(self) -> None:
        cur = QFont()
        fam, _, size = self.edit.text().partition(",")
        if fam:
            cur.setFamily(fam)
        if size.strip().replace(".", "").isdigit():
            cur.setPointSizeF(float(size))
        ok, f = QFontDialog.getFont(cur, self)
        if ok:
            self.edit.setText(f"{f.family()},{f.pointSize()}")


# Preview "Show:" choices: (label, Preview.popup key)
POPUPS = [("Desktop", ""), ("Launcher menu", "launcher"), ("Calendar", "calendar"),
          ("System tray", "tray"), ("Dialog", "dialog")]

# "Add common" tweaks: (submenu, label, [(file, group, key, value)]). Keys checked against KWin/Plasma 6.8 kcfg.
TWEAK_PRESETS = [
    ("Effects", "Wobbly windows", [("kwinrc", "Plugins", "wobblywindowsEnabled", True)]),
    ("Effects", "Magic lamp minimize", [("kwinrc", "Plugins", "magiclampEnabled", True),
                                        ("kwinrc", "Plugins", "squashEnabled", False)]),
    ("Effects", "Fall apart when closing", [("kwinrc", "Plugins", "fallapartEnabled", True)]),
    ("Effects", "Desktop cube", [("kwinrc", "Plugins", "cubeEnabled", True)]),
    ("Effects", "Dim inactive windows", [("kwinrc", "Plugins", "diminactiveEnabled", True)]),
    ("Effects", "Translucent inactive windows", [("kwinrc", "Plugins", "translucencyEnabled", True)]),
    ("Effects", "Shake cursor to find it", [("kwinrc", "Plugins", "shakecursorEnabled", True)]),
    ("Effects", "Stronger blur", [("kwinrc", "Plugins", "blurEnabled", True),
                                  ("kwinrc", "Effect-blur", "BlurStrength", 10)]),
    ("Effects", "Faster animations", [("kdeglobals", "KDE", "AnimationDurationFactor", 0.5)]),
    ("Effects", "No animations", [("kdeglobals", "KDE", "AnimationDurationFactor", 0)]),
    ("Windows", "Focus follows mouse", [("kwinrc", "Windows", "FocusPolicy", "FocusFollowsMouse")]),
    ("Windows", "No maximize when dragged to the top", [("kwinrc", "Windows", "ElectricBorderMaximize", False)]),
    ("Windows", "No tiling when dragged to an edge", [("kwinrc", "Windows", "ElectricBorderTiling", False)]),
    ("Windows", "No Overview hot corner", [("kwinrc", "Effect-overview", "BorderActivate", 9)]),
    ("Desktop", "Single click opens files", [("kdeglobals", "KDE", "SingleClick", True)]),
    ("Desktop", "Night Light on", [("kwinrc", "NightColor", "Active", True)]),
    ("Desktop", "Shorter notifications (3 s)", [("plasmanotifyrc", "Notifications", "PopupTimeout", 3000)]),
    ("Desktop", "Lock screen after 10 minutes", [("kscreenlockerrc", "Daemon", "Timeout", 10)]),
    ("Effects", "Glide windows open/closed", [("kwinrc", "Plugins", "glideEnabled", True),
                                              ("kwinrc", "Plugins", "scaleEnabled", False)]),
    ("Effects", "Fade between desktops", [("kwinrc", "Plugins", "fadedesktopEnabled", True),
                                          ("kwinrc", "Plugins", "slideEnabled", False)]),
    ("Effects", "Show mouse clicks", [("kwinrc", "Plugins", "mouseclickEnabled", True)]),
    ("Effects", "Sheet-style dialogs", [("kwinrc", "Plugins", "sheetEnabled", True),
                                        ("kwinrc", "Plugins", "dialogparentEnabled", True)]),
    ("Windows", "Open new windows centered", [("kwinrc", "Windows", "Placement", "Centered")]),
    ("Windows", "No title bars on maximized windows", [("kwinrc", "Windows", "BorderlessMaximizedWindows", True)]),
    ("Windows", "No window borders", [("kwinrc", "org.kde.kdecoration2", "BorderSize", "None"),
                                      ("kwinrc", "org.kde.kdecoration2", "BorderSizeAuto", False)]),
    ("Windows", "Thumbnail grid Alt+Tab", [("kwinrc", "TabBox", "LayoutName", "thumbnail_grid")]),
    ("Windows", "4 virtual desktops (2x2)", [("kwinrc", "Desktops", "Number", 4), ("kwinrc", "Desktops", "Rows", 2)]),
    ("Desktop", "Night Light warmer (3500 K)", [("kwinrc", "NightColor", "Active", True),
                                                ("kwinrc", "NightColor", "NightTemperature", 3500)]),
    ("Desktop", "Start with an empty session", [("ksmserverrc", "General", "loginMode", "emptySession")]),
    ("Desktop", "Scrollbar click jumps to the spot", [("kdeglobals", "KDE", "ScrollbarLeftClickNavigatesByPage", False)]),
]


def _tweak_text(v) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


def _tweak_value(text: str):
    """Table text -> TOML value: true/false, int, float, else string."""
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def combo(items: list[str]) -> QComboBox:
    c = QComboBox()
    c.setEditable(True)
    c.addItems(items)
    c.setInsertPolicy(QComboBox.NoInsert)
    return c


def scroll(widget: QWidget) -> QScrollArea:
    s = QScrollArea()
    s.setWidget(widget)
    s.setWidgetResizable(True)
    s.setFrameShape(QScrollArea.NoFrame)
    return s


# --- main window --------------------------------------------------------------------

class Main(QMainWindow):
    def __init__(self, path: str | None):
        super().__init__()
        self.path: Path | None = None
        self.theme = spec.Theme()
        self.dirty = False
        self._loading = False
        self.installed = system.summary()

        self.preview = Preview()
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._theme_tab(), "Theme")
        self.tabs.addTab(self._colors_tab(), "Colors")
        self.tabs.addTab(self._desktop_tab(), "Desktop")
        self.icons_tab = IconsTab(lambda: self.theme, lambda: self.path, self._ensure_saved)
        self.icons_tab.changed.connect(self.changed)
        self.icons_tab.icons_changed.connect(self._schedule_icons)
        self.icons_tab.generate.toggled.connect(lambda on: self.text["icons"].setEnabled(not on))
        self.tabs.addTab(scroll(self.icons_tab), "Icons")
        self.tabs.addTab(self._panels_tab(), "Panels")
        self.tabs.addTab(self._fonts_tab(), "Fonts")
        self.tabs.addTab(self._tweaks_tab(), "Tweaks")

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
        lv.addWidget(self.tabs, 1)
        left.setMinimumWidth(380)

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
        self.preview.popupChanged.connect(lambda key: self.popup.setCurrentIndex(max(0, self.popup.findData(key))))
        bar.addStretch()
        bar.addWidget(QLabel("Show:"))
        bar.addWidget(self.popup)
        rv.addLayout(bar)
        rv.addWidget(self.preview, 1)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([420, 860])
        split.setChildrenCollapsible(False)
        self.start = StartPage()
        self.start.new_theme.connect(self.new)
        self.start.from_desktop.connect(self.from_desktop)
        self.start.open_file.connect(self.open)
        self.start.open_path.connect(lambda p: self._open_path(Path(p)))
        self.start.open_starter.connect(lambda p: self.open_starter(Path(p)))
        self.start.manage.connect(self.manage_themes)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.start)
        self.stack.addWidget(split)
        self.setCentralWidget(self.stack)

        self._toolbar()
        self._log_dock()
        self.setStatusBar(self.statusBar())

        # Coalesce rapid edits (typing, dragging in the color dialog) into one repaint.
        self._refresh = QTimer(self, singleShot=True, interval=60)
        self._refresh.timeout.connect(lambda: self.preview.show_theme(self.theme))
        # The generated icon set is rebuilt into a cache dir for the preview (debounced: ~0.2 s per build).
        self._icons_timer = QTimer(self, singleShot=True, interval=500)
        self._icons_timer.timeout.connect(self._build_preview_icons)
        self._icons_key = None
        self._commit_timer = QTimer(self, singleShot=True, interval=600)
        self._commit_timer.timeout.connect(self._commit)
        self._check_timer = QTimer(self, singleShot=True, interval=400)
        self._check_timer.timeout.connect(self._update_problems)

        self.to_form()
        if path:
            self.load(Path(path))
        if self.path:
            self.show_editor()
        else:
            self.show_start()
        self._update_title()

    # --- chrome ---------------------------------------------------------------------
    def _toolbar(self) -> None:
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
                              "Pack a shareable .tar.gz with the wallpaper")
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
        act("Undo Apply", "edit-undo", self.revert, None,
            "Put the desktop back the way it was before the last Apply (every install takes a restore point)")
        act("Installed…", "preferences-desktop-theme-global", self.manage_themes, None,
            "See and remove the themes kde-customizer has installed")
        self._editor_actions = [self.save_act, self.saveas_act, self.undo_act, self.redo_act, self.build_act, self.export_act,
                                self.apply_act, self.with_layout]

    def _log_dock(self) -> None:
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

    # --- tabs -----------------------------------------------------------------------
    def _form_page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(12)
        return page, v

    def _group(self, title: str, parent: QVBoxLayout) -> QFormLayout:
        g = QGroupBox(title)
        f = QFormLayout(g)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        parent.addWidget(g)
        return f

    def _line(self, form: QFormLayout, label: str, attr: str, placeholder: str = "") -> QLineEdit:
        w = QLineEdit(placeholderText=placeholder)
        w.textChanged.connect(self.changed)
        form.addRow(label, w)
        self.text[attr] = w
        return w

    def _theme_tab(self) -> QWidget:
        self.text: dict[str, QLineEdit | QComboBox] = {}
        page, v = self._form_page()
        f = self._group("Identity", v)
        self._line(f, "Name", "name")
        self._line(f, "ID", "id", "org.example.mytheme")
        self._line(f, "Author", "author")
        self._line(f, "Version", "version")
        self.description = QPlainTextEdit()
        self.description.setMaximumHeight(80)
        self.description.textChanged.connect(self.changed)
        f.addRow("Description", self.description)
        v.addStretch()
        return scroll(page)

    def _colors_tab(self) -> QWidget:
        page, v = self._form_page()
        f = self._group("Palette", v)
        self.colors: dict[str, ColorField] = {}
        hints = {
            "background": "Windows, panels", "surface": "Title bars, buttons, headers",
            "foreground": "Text", "accent": "Selection, focus, highlights",
            "positive": "Success", "neutral": "Warnings", "negative": "Errors, close button",
        }
        for fld in fields(spec.Palette):
            if fld.name in ("link", "visited"):
                continue
            cf = ColorField()
            cf.setToolTip(hints.get(fld.name, ""))
            cf.changed.connect(self.changed)
            self.colors[fld.name] = cf
            lbl = QLabel(fld.name.title())
            lbl.setToolTip(hints.get(fld.name, ""))
            f.addRow(lbl, cf)
        pick = QToolButton(text="Colors from an image", icon=QIcon.fromTheme("color-picker"),
                           toolButtonStyle=Qt.ToolButtonTextBesideIcon, popupMode=QToolButton.InstantPopup)
        pick.setToolTip("Make a readable palette from a picture: the background takes its main hue, the accent "
                        "its most colorful part")
        menu = QMenu(pick)
        self.img_wallpaper = menu.addAction(QIcon.fromTheme("preferences-desktop-wallpaper"),
                                            "From this theme's wallpaper", lambda: self.palette_from_image(None))
        menu.addAction(QIcon.fromTheme("document-open"), "From an image…", self.palette_from_image_file)
        menu.addSeparator()
        self.img_mode = QActionGroup(menu)
        for label, data in [("Dark or light: like the image", None), ("Dark theme", True), ("Light theme", False)]:
            a = menu.addAction(label)
            a.setCheckable(True)
            a.setData(data)
            a.setChecked(data is None)
            self.img_mode.addAction(a)
        menu.aboutToShow.connect(lambda: self.img_wallpaper.setEnabled(bool(self.theme.wallpaper)))
        pick.setMenu(menu)
        v.addWidget(pick, 0, Qt.AlignLeft)
        self.contrast = QLabel()
        self.contrast.setWordWrap(True)
        self.contrast.setTextFormat(Qt.RichText)
        v.addWidget(self.contrast)
        v.addStretch()
        return scroll(page)

    def _desktop_tab(self) -> QWidget:
        page, v = self._form_page()

        f = self._group("Wallpaper", v)
        row = QHBoxLayout()
        self.text["wallpaper"] = QLineEdit(placeholderText="none — preview uses a palette gradient")
        self.text["wallpaper"].textChanged.connect(self.changed)
        browse = QPushButton(QIcon.fromTheme("document-open"), "")
        browse.setToolTip("Choose image…")
        browse.clicked.connect(self.pick_wallpaper)
        self.wp_make = QPushButton(QIcon.fromTheme("games-config-background"), "Make…")
        self.wp_make.setToolTip("Render a wallpaper in this palette with your local image AI (the one set up "
                                "in the Icons tab: Fooocus, ComfyUI or A1111/Forge)")
        self.wp_make.clicked.connect(self.make_wallpaper)
        row.addWidget(self.text["wallpaper"])
        row.addWidget(browse)
        row.addWidget(self.wp_make)
        f.addRow("Image", row)

        f = self._group("Plasma style", v)
        self.plasma: dict[str, QCheckBox] = {}
        for key, label in [("generate", "Generate from palette"),
                           ("blur", "Blur behind panels and popups"),
                           ("adaptive_transparency", "Opaque panels when a window is maximized")]:
            self.plasma[key] = QCheckBox(label)
            self.plasma[key].toggled.connect(self.changed)
            f.addRow(self.plasma[key])
        self.p_radius = QSpinBox(minimum=0, maximum=32, suffix=" px",
                                 toolTip="Corner radius of floating panels, popups and tooltips")
        self.p_opacity = QSpinBox(minimum=30, maximum=100, suffix=" %",
                                  toolTip="Fill opacity of panels and popups (Breeze: 85 %)")
        for w in (self.p_radius, self.p_opacity):
            w.valueChanged.connect(self.changed)
        f.addRow("Corner radius", self.p_radius)
        f.addRow("Opacity", self.p_opacity)
        self.plasma["outline"] = QCheckBox("Outline panels and popups")
        self.plasma["outline"].toggled.connect(self.changed)
        f.addRow(self.plasma["outline"])
        self.text["plasma_style"] = combo(self.installed["plasma_style"])
        f.addRow("Installed style", self.text["plasma_style"])
        self.plasma["generate"].toggled.connect(self._plasma_generate_toggled)

        f = self._group("App style", v)
        self.w_generate = QCheckBox("Generate a Kvantum style from palette")
        self.w_generate.setToolTip("Buttons, fields, menus and tabs drawn in the theme's colors. Needs the "
                                   "kvantum package; without it apps keep the App style chosen below.")
        self.w_generate.toggled.connect(self.changed)
        self.w_generate.toggled.connect(lambda on: self.w_radius.setEnabled(on))
        f.addRow(self.w_generate)
        self.w_radius = QSpinBox(minimum=0, maximum=12, suffix=" px",
                                 toolTip="Corner radius of buttons, fields, menus, tabs and check boxes")
        self.w_radius.valueChanged.connect(self.changed)
        f.addRow("Corner radius", self.w_radius)
        if not system.kvantum_installed():
            note = QLabel("Kvantum isn't installed here, so the preview and this machine keep the "
                          "fallback style. The theme still includes it for others.")
            note.setWordWrap(True)
            note.setStyleSheet("color: palette(placeholder-text)")
            f.addRow(note)

        f = self._group("Look", v)
        for attr, label in [("icons", "Icons"), ("cursors", "Cursors"), ("widget_style", "App style")]:
            c = combo(self.installed[attr])
            c.currentTextChanged.connect(self.changed)
            self.text[attr] = c
            f.addRow(label, c)
        self._line(f, "Splash", "splash")
        self.konsole = QCheckBox("Matching Konsole color scheme")
        self.konsole.toggled.connect(self.changed)
        f.addRow(self.konsole)
        self.g_generate = QCheckBox("Matching GNOME / GTK 4 apps")
        self.g_generate.setToolTip("libadwaita apps ignore KDE color schemes; this gives them the palette "
                                   "through ~/.config/gtk-4.0")
        self.g_generate.toggled.connect(self.changed)
        self.g_generate.toggled.connect(lambda on: self.g_flatpak.setEnabled(on))
        f.addRow(self.g_generate)
        self.g_flatpak = QCheckBox("Flatpak GNOME apps too")
        self.g_flatpak.setToolTip("Gives Flatpak apps read-only access to ~/.config/gtk-4.0 "
                                  "(flatpak override --user)")
        self.g_flatpak.toggled.connect(self.changed)
        f.addRow(self.g_flatpak)
        self.light_dark = QCheckBox("Light and dark versions, switched by time of day")
        self.light_dark.setToolTip("Also builds the opposite version (same hues) and lets Plasma switch between "
                                   "the two at sunrise and sunset (Night Light's schedule). GTK apps, terminals "
                                   "and Konsole follow; apps use the fallback style instead of Kvantum.")
        self.light_dark.toggled.connect(self.changed)
        f.addRow(self.light_dark)

        f = self._group("Other terminals and editors", v)
        note = QLabel("Matching colors for these apps, when they are installed.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(placeholder-text)")
        f.addRow(note)
        self.apps: dict[str, QCheckBox] = {}
        for key, label, tip in [
            ("kitty", "kitty", "Theme file + an include at the end of kitty.conf"),
            ("alacritty", "Alacritty", "Imports a theme; alacritty.toml's own [colors.*] tables are commented out "
                                       "(backup kept, restored when this is off)"),
            ("wezterm", "WezTerm", "Installs a color scheme; select it in wezterm.lua"),
            ("ghostty", "Ghostty", "Theme file + `theme =` at the end of Ghostty's config"),
            ("vscode", "VS Code / VSCodium", "Installs a theme extension; pick it in Preferences > Color Theme"),
            ("firefox", "Firefox / LibreWolf", "Toolbar, tabs, address bar and menus via each profile's "
                                               "userChrome.css; restart the browser to see it"),
            ("thunderbird", "Thunderbird", "Via each profile's userChrome.css; restart Thunderbird to see it"),
        ]:
            c = QCheckBox(label)
            c.setToolTip(tip)
            c.toggled.connect(self.changed)
            self.apps[key] = c
            f.addRow(c)

        f = self._group("Cursors", v)
        self.c_generate = QCheckBox("Generate cursors from palette")
        self.c_generate.setToolTip("Recolor an SVG cursor theme to the palette (replaces Cursors above)")
        self.c_generate.toggled.connect(self.changed)
        self.c_generate.toggled.connect(self._cursor_generate_toggled)
        f.addRow(self.c_generate)
        self.c_base = combo(cursorset.scalable_themes() or ["breeze_cursors"])
        self.c_base.setToolTip("Installed cursor theme with SVG cursors to recolor")
        self.c_base.currentTextChanged.connect(self.changed)
        f.addRow("Base", self.c_base)
        self.c_fill = QComboBox()
        self.c_fill.addItems(list(spec.CursorSet.FILLS))
        self.c_fill.setToolTip("Pointer body color; the outline takes the contrasting palette color")
        self.c_fill.currentTextChanged.connect(self.changed)
        f.addRow("Body", self.c_fill)

        f = self._group("Splash screen", v)
        self.s_generate = QCheckBox("Generate a splash screen from palette")
        self.s_generate.setToolTip("Theme name and a progress bar in the palette's colors "
                                   "(replaces the Splash above)")
        self.s_generate.toggled.connect(self.changed)
        self.s_generate.toggled.connect(self._splash_generate_toggled)
        f.addRow(self.s_generate)
        self.s_background = QComboBox()
        self.s_background.addItems(list(spec.SplashScreen.BACKGROUNDS))
        self.s_background.setToolTip("wallpaper uses the theme's wallpaper, dimmed; without one it falls "
                                     "back to the gradient")
        self.s_background.currentTextChanged.connect(self.changed)
        f.addRow("Background", self.s_background)
        self.s_text = QLineEdit(placeholderText="the theme name")
        self.s_text.textChanged.connect(self.changed)
        f.addRow("Text", self.s_text)

        f = self._group("Boot splash", v)
        self.b_generate = QCheckBox("Generate a boot splash (Plymouth)")
        self.b_generate.setToolTip("Theme name and a progress bar while booting and at disk-unlock prompts. "
                                   "Installing asks for the admin password and rebuilds the initramfs.")
        self.b_generate.toggled.connect(self.changed)
        self.b_generate.toggled.connect(lambda on: (self.b_background.setEnabled(on), self.b_text.setEnabled(on)))
        f.addRow(self.b_generate)
        self.b_background = QComboBox()
        self.b_background.addItems(list(spec.BootSplash.BACKGROUNDS))
        self.b_background.currentTextChanged.connect(self.changed)
        f.addRow("Background", self.b_background)
        self.b_text = QLineEdit(placeholderText="the theme name")
        self.b_text.textChanged.connect(self.changed)
        f.addRow("Text", self.b_text)

        f = self._group("Login screen", v)
        self.l_generate = QCheckBox("Theme the login screen")
        self.l_generate.setToolTip("Colors, Plasma style, icons, cursors and wallpaper on the login screen "
                                   "(Plasma Login Manager or SDDM). Installing asks for the admin password (only when it changed).")
        self.l_generate.toggled.connect(self.changed)
        self.l_generate.toggled.connect(self._login_generate_toggled)
        f.addRow(self.l_generate)
        self.l_background = QComboBox()
        self.l_background.addItems(list(spec.LoginScreen.BACKGROUNDS))
        self.l_background.setToolTip("wallpaper = the theme's wallpaper (palette color without one); "
                                     "color = the palette background")
        self.l_background.currentTextChanged.connect(self.changed)
        f.addRow("Background", self.l_background)
        self.l_clock = QCheckBox("Show the clock")
        self.l_clock.toggled.connect(self.changed)
        f.addRow(self.l_clock)

        f = self._group("Window decoration", v)
        self.deco: dict[str, QLineEdit] = {}
        for attr, label, tip in [
            ("library", "Library", ""), ("theme", "Theme", ""),
            ("buttons_left", "Left buttons", "M menu · S all desktops · H help · F above · B below · _ spacer"),
            ("buttons_right", "Right buttons", "I minimize · A maximize · X close"),
        ]:
            w = QLineEdit()
            w.setToolTip(tip)
            w.textChanged.connect(self.changed)
            self.deco[attr] = w
            f.addRow(label, w)
        self.d_generate = QCheckBox("Generate title bars from palette")
        self.d_generate.setToolTip("Build an Aurorae window decoration in the theme's colors "
                                   "(replaces Library/Theme above)")
        self.d_generate.toggled.connect(self.changed)
        self.d_generate.toggled.connect(self._deco_generate_toggled)
        f.addRow(self.d_generate)
        self.d_radius = QSpinBox(minimum=0, maximum=16, suffix=" px", toolTip="Top corner radius")
        self.d_height = QSpinBox(minimum=20, maximum=60, suffix=" px", toolTip="Title bar height")
        self.d_border = QSpinBox(minimum=0, maximum=12, suffix=" px", toolTip="Side and bottom border (0 = none)")
        self.d_align = QComboBox()
        self.d_align.addItems(list(spec.Decoration.TITLE_ALIGNS))
        self.d_style = QComboBox()
        self.d_style.addItems(list(spec.Decoration.BUTTON_STYLES))
        self.d_style.setToolTip("glyph: symbols with a round hover · dots: colored circles "
                                "(close = negative, minimize = neutral, maximize = positive)")
        for w in (self.d_radius, self.d_height, self.d_border):
            w.valueChanged.connect(self.changed)
        for w in (self.d_align, self.d_style):
            w.currentTextChanged.connect(self.changed)
        f.addRow("Corner radius", self.d_radius)
        f.addRow("Title height", self.d_height)
        f.addRow("Border", self.d_border)
        f.addRow("Title align", self.d_align)
        f.addRow("Buttons", self.d_style)
        v.addStretch()
        return scroll(page)

    def _login_generate_toggled(self, on: bool) -> None:
        self.l_background.setEnabled(on)
        self.l_clock.setEnabled(on)

    def _cursor_generate_toggled(self, on: bool) -> None:
        self.text["cursors"].setEnabled(not on)
        self.c_base.setEnabled(on)
        self.c_fill.setEnabled(on)

    def _splash_generate_toggled(self, on: bool) -> None:
        self.text["splash"].setEnabled(not on)
        self.s_background.setEnabled(on)
        self.s_text.setEnabled(on)

    def _deco_generate_toggled(self, on: bool) -> None:
        for w in (self.deco["library"], self.deco["theme"]):
            w.setEnabled(not on)
        for w in (self.d_radius, self.d_height, self.d_border, self.d_align, self.d_style):
            w.setEnabled(on)

    def _panels_tab(self) -> QWidget:
        page, v = self._form_page()
        top = QHBoxLayout()
        self.panel_list = QListWidget()
        self.panel_list.setMaximumHeight(90)
        self.panel_list.currentRowChanged.connect(self._panel_selected)
        btns = QVBoxLayout()
        add = QPushButton(QIcon.fromTheme("list-add"), "Add")
        add.clicked.connect(self._add_panel)
        rem = QPushButton(QIcon.fromTheme("list-remove"), "Remove")
        rem.clicked.connect(self._remove_panel)
        btns.addWidget(add)
        btns.addWidget(rem)
        btns.addStretch()
        top.addWidget(self.panel_list, 1)
        top.addLayout(btns)
        v.addLayout(top)

        self.panel_box = QGroupBox("Panel")
        f = QFormLayout(self.panel_box)
        self.p_location = QComboBox()
        self.p_location.addItems(["bottom", "top", "left", "right"])
        self.p_height = QSpinBox(minimum=20, maximum=120, suffix=" px")
        self.p_floating = QCheckBox("Floating")
        self.p_align = QComboBox()
        self.p_align.addItems(["left", "center", "right"])
        self.p_length = QComboBox()
        self.p_length.addItems(["fill", "fit"])
        f.addRow("Position", self.p_location)
        f.addRow("Thickness", self.p_height)
        f.addRow(self.p_floating)
        f.addRow("Alignment", self.p_align)
        f.addRow("Width", self.p_length)
        for w in (self.p_location, self.p_align, self.p_length):
            w.currentTextChanged.connect(self._panel_edited)
        self.p_height.valueChanged.connect(self._panel_edited)
        self.p_floating.toggled.connect(self._panel_edited)

        self.p_widgets = QListWidget()
        self.p_widgets.setDragDropMode(QAbstractItemView.InternalMove)
        self.p_widgets.model().rowsMoved.connect(self._panel_edited)
        f.addRow(QLabel("Widgets (drag to reorder)"))
        f.addRow(self.p_widgets)
        wrow = QHBoxLayout()
        self.p_new_widget = combo(COMMON_WIDGETS)
        addw = QPushButton(QIcon.fromTheme("list-add"), "")
        addw.clicked.connect(self._add_widget)
        remw = QPushButton(QIcon.fromTheme("list-remove"), "")
        remw.clicked.connect(self._remove_widget)
        wrow.addWidget(self.p_new_widget, 1)
        wrow.addWidget(addw)
        wrow.addWidget(remw)
        f.addRow(wrow)
        v.addWidget(self.panel_box)
        v.addStretch()
        return scroll(page)

    def _fonts_tab(self) -> QWidget:
        page, v = self._form_page()
        f = self._group("Fonts", v)
        self.fonts: dict[str, FontField] = {}
        for fld in fields(spec.Fonts):
            ff = FontField()
            ff.changed.connect(self.changed)
            self.fonts[fld.name] = ff
            f.addRow(fld.name.replace("_", " ").capitalize(), ff)
        v.addStretch()
        return scroll(page)

    def _tweaks_tab(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        note = QLabel("Any KDE setting, written with kwriteconfig6 when the theme is installed. "
                      "Nested groups use “/”, e.g. Effect-blur or Containments/1.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(placeholder-text)")
        v.addWidget(note)
        self.tweaks = QTableWidget(0, 4)
        self.tweaks.setHorizontalHeaderLabels(["File", "Group", "Key", "Value"])
        self.tweaks.verticalHeader().hide()
        h = self.tweaks.horizontalHeader()
        for col in range(3):
            h.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        self.tweaks.itemChanged.connect(self.changed)
        v.addWidget(self.tweaks, 1)
        row = QHBoxLayout()
        common = QToolButton(text="Add common", icon=QIcon.fromTheme("list-add"),
                             toolButtonStyle=Qt.ToolButtonTextBesideIcon, popupMode=QToolButton.InstantPopup)
        menu = QMenu(common)
        subs: dict[str, QMenu] = {}
        for sub, label, entries in TWEAK_PRESETS:
            if sub not in subs:
                subs[sub] = menu.addMenu(sub)
            subs[sub].addAction(label, lambda e=entries: self._add_tweaks(e))
        common.setMenu(menu)
        add = QPushButton(QIcon.fromTheme("list-add"), "Add row")
        add.clicked.connect(lambda: self._add_tweaks([("kwinrc", "", "", "")], edit=True))
        rem = QPushButton(QIcon.fromTheme("list-remove"), "Remove")
        rem.clicked.connect(self._remove_tweaks)
        row.addWidget(common)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch()
        v.addLayout(row)
        return page

    def _add_tweaks(self, entries, edit: bool = False) -> None:
        """Append rows; an existing file/group/key gets its value replaced instead."""
        self.tweaks.blockSignals(True)
        for f, g, k, val in entries:
            r = next((i for i in range(self.tweaks.rowCount()) if k and
                      [self._cell(i, c) for c in range(3)] == [f, g, k]), None)
            if r is None:
                r = self.tweaks.rowCount()
                self.tweaks.insertRow(r)
            for c, text in enumerate((f, g, k, _tweak_text(val))):
                self.tweaks.setItem(r, c, QTableWidgetItem(text))
        self.tweaks.blockSignals(False)
        if edit:
            self.tweaks.setCurrentCell(self.tweaks.rowCount() - 1, 1)
            self.tweaks.editItem(self.tweaks.currentItem())
        self.changed()

    def _remove_tweaks(self) -> None:
        rows = sorted({i.row() for i in self.tweaks.selectedIndexes()}, reverse=True)
        for r in rows:
            self.tweaks.removeRow(r)
        if rows:
            self.changed()

    def _cell(self, r: int, c: int) -> str:
        it = self.tweaks.item(r, c)
        return it.text().strip() if it else ""

    def _tweaks_to_form(self, tweaks: dict) -> None:
        self.tweaks.blockSignals(True)
        self.tweaks.setRowCount(0)
        self.tweaks.blockSignals(False)
        self._add_tweaks([(f, g, k, v) for f, groups in tweaks.items()
                          for g, kv in groups.items() for k, v in kv.items()])

    def _tweaks_from_form(self) -> dict:
        out: dict = {}
        for r in range(self.tweaks.rowCount()):
            f, g, k, val = (self._cell(r, c) for c in range(4))
            if f and g and k:                      # half-filled rows are ignored until complete
                out.setdefault(f, {}).setdefault(g, {})[k] = _tweak_value(val)
        return out

    # --- panels editing (writes straight into self.theme.panels) ----------------------
    def _panel_label(self, p: spec.Panel) -> str:
        return f"{p.location.title()} panel · {p.height}px{' · floating' if p.floating else ''}"

    def _fill_panel_list(self, select: int = 0) -> None:
        self.panel_list.blockSignals(True)
        self.panel_list.clear()
        for p in self.theme.panels:
            self.panel_list.addItem(self._panel_label(p))
        self.panel_list.blockSignals(False)
        self.panel_box.setEnabled(bool(self.theme.panels))
        if self.theme.panels:
            self.panel_list.setCurrentRow(min(select, len(self.theme.panels) - 1))
            self._panel_selected(self.panel_list.currentRow())

    def _panel_selected(self, row: int) -> None:
        if row < 0 or row >= len(self.theme.panels):
            return
        p = self.theme.panels[row]
        self._loading, was = True, self._loading
        self.p_location.setCurrentText(p.location)
        self.p_height.setValue(p.height)
        self.p_floating.setChecked(p.floating)
        self.p_align.setCurrentText(p.alignment)
        self.p_length.setCurrentText(p.length_mode)
        self.p_widgets.clear()
        self.p_widgets.addItems(p.widgets)
        self._loading = was

    def _panel_edited(self, *_) -> None:
        row = self.panel_list.currentRow()
        if self._loading or row < 0:
            return
        p = self.theme.panels[row]
        p.location = self.p_location.currentText()
        p.height = self.p_height.value()
        p.floating = self.p_floating.isChecked()
        p.alignment = self.p_align.currentText()
        p.length_mode = self.p_length.currentText()
        p.widgets = [self.p_widgets.item(i).text() for i in range(self.p_widgets.count())]
        self.panel_list.item(row).setText(self._panel_label(p))
        self.changed()

    def _add_panel(self) -> None:
        used = {p.location for p in self.theme.panels}
        loc = next((l for l in ("bottom", "top", "left", "right") if l not in used), "top")
        self.theme.panels.append(spec.Panel(location=loc, widgets=[] if self.theme.panels else spec.Panel().widgets))
        self._fill_panel_list(len(self.theme.panels) - 1)
        self.changed()

    def _remove_panel(self) -> None:
        row = self.panel_list.currentRow()
        if row >= 0:
            del self.theme.panels[row]
            self._fill_panel_list(max(0, row - 1))
            self.changed()

    def _add_widget(self) -> None:
        w = self.p_new_widget.currentText().strip()
        if w:
            self.p_widgets.addItem(w)
            self._panel_edited()

    def _remove_widget(self) -> None:
        for item in self.p_widgets.selectedItems():
            self.p_widgets.takeItem(self.p_widgets.row(item))
        self._panel_edited()

    # --- form <-> theme ---------------------------------------------------------------
    def to_form(self) -> None:
        self._loading = True
        t = self.theme
        for k, w in self.text.items():
            val = getattr(t, k)
            w.setCurrentText(val) if isinstance(w, QComboBox) else w.setText(val)
        self.description.setPlainText(t.description)
        for k, cf in self.colors.items():
            cf.set(getattr(t.palette, k))
        for k, c in self.plasma.items():
            c.setChecked(getattr(t.plasma, k))
        self.s_generate.setChecked(t.splash_screen.generate)
        self.s_background.setCurrentText(t.splash_screen.background)
        self.s_text.setText(t.splash_screen.text)
        self._splash_generate_toggled(t.splash_screen.generate)
        self.b_generate.setChecked(t.boot_splash.generate)
        self.b_background.setCurrentText(t.boot_splash.background)
        self.b_text.setText(t.boot_splash.text)
        self.b_background.setEnabled(t.boot_splash.generate)
        self.b_text.setEnabled(t.boot_splash.generate)
        self.l_generate.setChecked(t.login_screen.generate)
        self.l_background.setCurrentText(t.login_screen.background)
        self.l_clock.setChecked(t.login_screen.clock)
        self._login_generate_toggled(t.login_screen.generate)
        self.c_generate.setChecked(t.cursorset.generate)
        self.c_base.setCurrentText(t.cursorset.base)
        self.c_fill.setCurrentText(t.cursorset.fill)
        self._cursor_generate_toggled(t.cursorset.generate)
        self.w_generate.setChecked(t.widgets.generate)
        self.w_radius.setValue(t.widgets.radius)
        self.w_radius.setEnabled(t.widgets.generate)
        self.p_radius.setValue(t.plasma.radius)
        self.p_opacity.setValue(round(t.plasma.opacity * 100))
        self._plasma_generate_toggled(t.plasma.generate)
        self.konsole.setChecked(t.konsole)
        self.g_generate.setChecked(t.gtk.generate)
        for k, c in self.apps.items():
            c.setChecked(getattr(t.apps, k))
        self.g_flatpak.setChecked(t.gtk.flatpak)
        self.g_flatpak.setEnabled(t.gtk.generate)
        self.light_dark.setChecked(t.light_dark.auto)
        for k, w in self.deco.items():
            w.setText(getattr(t.decoration, k))
        d = t.decoration
        self.d_generate.setChecked(d.generate)
        self.d_radius.setValue(d.radius)
        self.d_height.setValue(d.title_height)
        self.d_border.setValue(d.border)
        self.d_align.setCurrentText(d.title_align)
        self.d_style.setCurrentText(d.button_style)
        self._deco_generate_toggled(d.generate)
        for k, ff in self.fonts.items():
            ff.edit.setText(getattr(t.fonts, k))
        self._fill_panel_list()
        self._tweaks_to_form(t.tweaks)
        self.icons_tab.load(t)
        self.text["icons"].setEnabled(not t.iconset.generate)
        self._loading = False
        self._after_change()

    def _plasma_generate_toggled(self, on: bool) -> None:
        """Shape options only exist for the generated style; the installed one is used otherwise."""
        self.text["plasma_style"].setEnabled(not on)
        for w in (self.p_radius, self.p_opacity, self.plasma["outline"]):
            w.setEnabled(on)

    def from_form(self) -> spec.Theme:
        t = self.theme
        for k, w in self.text.items():
            setattr(t, k, (w.currentText() if isinstance(w, QComboBox) else w.text()).strip())
        t.description = self.description.toPlainText().strip()
        for k, cf in self.colors.items():
            try:
                color.parse(cf.value)
                setattr(t.palette, k, cf.value)
            except ValueError:
                pass  # keep last valid color while the user is mid-typing
        for k, c in self.plasma.items():
            setattr(t.plasma, k, c.isChecked())
        t.splash_screen.generate = self.s_generate.isChecked()
        t.splash_screen.background = self.s_background.currentText()
        t.splash_screen.text = self.s_text.text().strip()
        t.boot_splash.generate = self.b_generate.isChecked()
        t.boot_splash.background = self.b_background.currentText()
        t.boot_splash.text = self.b_text.text().strip()
        t.login_screen.generate = self.l_generate.isChecked()
        t.login_screen.background = self.l_background.currentText()
        t.login_screen.clock = self.l_clock.isChecked()
        t.cursorset.generate = self.c_generate.isChecked()
        t.cursorset.base = self.c_base.currentText().strip() or "breeze_cursors"
        t.cursorset.fill = self.c_fill.currentText()
        t.widgets.generate = self.w_generate.isChecked()
        t.widgets.radius = self.w_radius.value()
        t.plasma.radius = self.p_radius.value()
        t.plasma.opacity = self.p_opacity.value() / 100
        t.konsole = self.konsole.isChecked()
        t.gtk.generate = self.g_generate.isChecked()
        for k, c in self.apps.items():
            setattr(t.apps, k, c.isChecked())
        t.gtk.flatpak = self.g_flatpak.isChecked()
        t.light_dark.auto = self.light_dark.isChecked()
        t.tweaks = self._tweaks_from_form()
        for k, w in self.deco.items():
            setattr(t.decoration, k, w.text().strip())
        d = t.decoration
        d.generate = self.d_generate.isChecked()
        d.title_height = self.d_height.value()
        d.radius = min(self.d_radius.value(), d.title_height // 2)
        d.border = self.d_border.value()
        d.title_align = self.d_align.currentText()
        d.button_style = self.d_style.currentText()
        for k, ff in self.fonts.items():
            setattr(t.fonts, k, ff.edit.text().strip())
        self.icons_tab.store(t)
        return t

    def changed(self, *_) -> None:
        if self._loading:
            return
        self.from_form()
        if not self.dirty:
            self.dirty = True
            self._update_title()
        self._commit_timer.start()
        self._after_change()

    def _after_change(self) -> None:
        self._refresh.start()
        self._update_contrast()
        self._check_timer.start()
        ics = self.theme.iconset
        key = (ics.generate, ics.base, ics.signature_dir, ics.app_icons, self.theme.palette.accent, self.theme.slug)
        if ics.generate and key != self._icons_key:
            self._icons_timer.start()

    def _schedule_icons(self) -> None:
        self._icons_key = None
        self._icons_timer.start()

    def _build_preview_icons(self) -> None:
        """Build the generated icon theme into a cache dir the preview's icon lookup searches."""
        t = self.theme
        if not t.iconset.generate:
            return
        root = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation)) / "preview-icons"
        try:
            iconset.build(t, root, only=iconset.preview_names())  # just what the preview draws
        except Exception as e:  # missing base theme, unreadable files…
            self.statusBar().showMessage(f"Icon preview: {e}", 6000)
            return
        ics = t.iconset
        self._icons_key = (ics.generate, ics.base, ics.signature_dir, ics.app_icons, t.palette.accent, t.slug)
        paths = [p for p in QIcon.themeSearchPaths() if p != str(root)]
        QIcon.setThemeSearchPaths([str(root), *paths])  # also makes Qt drop its cached lookups
        self.preview.icons.clear()
        self.preview.update()

    def _ensure_saved(self) -> bool:
        """Signature icons are stored next to the spec, so it needs a file first."""
        if self.path and not self.dirty:
            return True
        return self.save()          # first save names the theme and puts it in the themes folder

    def _update_contrast(self) -> None:
        p = self.theme.palette.resolved()
        checks = [("Text on background", p.foreground, p.background, 4.5),
                  ("Text on surface", p.foreground, p.surface, 4.5),
                  ("Accent on background", p.accent, p.background, 3.0)]
        rows = []
        for label, a, b, need in checks:
            try:
                r = color.contrast(a, b)
            except ValueError:
                continue
            mark = "✓" if r >= need else "⚠ low"
            col = "" if r >= need else " style='color:#d4351c'"
            rows.append(f"<tr><td>{label}</td><td align=right{col}>&nbsp;&nbsp;{r:.1f}:1 {mark}</td></tr>")
        mode = "Dark" if self.theme.dark else "Light"
        self.contrast.setText(f"<b>{mode} theme</b> — readability (WCAG contrast)<table>{''.join(rows)}</table>")

    def _update_problems(self) -> None:
        """`kdec check` on the theme being edited; each problem links to the tab where it's fixed."""
        try:
            found = ai.check(self.theme, self.installed)
        except Exception:           # half-typed values: check again on the next edit
            return
        tabs = {"contrast": 1, "iconset": 3, "icons": 2, "cursor": 2, "widget": 2, "plasma": 2, "splash": 2,
                "login": 2, "wallpaper": 2}

        def tab(p: str) -> int:
            return next((i for k, i in tabs.items() if p.startswith(k) or p.split()[0].startswith(k)), 1)
        names = [self.tabs.tabText(i) for i in range(self.tabs.count())]

        def text(p: str) -> str:        # the full lists of installed themes are too long for the strip
            return html.escape(re.sub(r" \((installed|usable): [^)]*\)", "", p))
        items = "".join(f"<li>{text(p)} — <a href='tab:{tab(p)}'>{names[tab(p)]}</a></li>" for p in found)
        n = len(found)
        self.problems.setText(f"<b>⚠ {n} thing{'s' if n > 1 else ''} to check</b>"
                              f"<ul style='margin:2px 0 0 -20px'>{items}</ul>")
        self.problems.setVisible(bool(found))

    # --- undo / redo --------------------------------------------------------------
    def _commit(self) -> None:
        """Make the current theme one undo step (if it changed since the last one)."""
        self._commit_timer.stop()
        if self.theme == self._committed:
            return
        self._undo_stack.append(self._committed)
        del self._undo_stack[:-100]
        self._committed = copy.deepcopy(self.theme)
        self._redo_stack.clear()
        self._update_undo()

    def _reset_history(self) -> None:
        self._commit_timer.stop()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._committed = copy.deepcopy(self.theme)
        self._update_undo()

    def _update_undo(self) -> None:
        self.undo_act.setEnabled(bool(self._undo_stack) and self.stack.currentIndex() == 1)
        self.redo_act.setEnabled(bool(self._redo_stack) and self.stack.currentIndex() == 1)
        self.ai.undo.setEnabled(bool(self._undo_stack))

    def _step_to(self, theme: spec.Theme) -> None:
        tab = self.tabs.currentIndex()
        self.set_theme(copy.deepcopy(theme), True)
        self.tabs.setCurrentIndex(tab)
        self._update_undo()

    def undo(self) -> None:
        self._commit()
        if self._undo_stack:
            self._redo_stack.append(self._committed)
            self._committed = self._undo_stack.pop()
            self._step_to(self._committed)

    def redo(self) -> None:
        self._commit()
        if self._redo_stack:
            self._undo_stack.append(self._committed)
            self._committed = self._redo_stack.pop()
            self._step_to(self._committed)

    # --- start page -----------------------------------------------------------------
    def show_start(self) -> None:
        self.start.refresh()
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

    def _open_path(self, path: Path) -> None:
        if path == self.path and not self.dirty:
            self.show_editor()
        elif self._confirm_discard():
            self.load(path)

    def open_starter(self, path: Path) -> None:
        """A built-in starting point opens as a new, unsaved theme (first Save names it)."""
        if not self._confirm_discard():
            return
        try:
            theme = spec.load(path)
        except Exception as e:
            QMessageBox.critical(self, "Load failed", str(e))
            return
        self.path = None
        self._fresh(theme, False)

    def manage_themes(self) -> None:
        ThemeManager(self).exec()

    # --- palette from an image --------------------------------------------------------
    def palette_from_image_file(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Colors from an image", str(Path.home()),
                                           "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if f:
            self.palette_from_image(Path(f))

    def palette_from_image(self, path: Path | None) -> None:
        from .. import imagepalette
        path = path or Path(self.theme.wallpaper).expanduser()
        try:
            pal = imagepalette.from_image(path, self.img_mode.checkedAction().data(), self.theme.palette)
        except Exception as e:      # unreadable image
            QMessageBox.warning(self, "Colors from an image", str(e))
            return
        self._commit()
        self._loading = True
        for k, cf in self.colors.items():
            cf.set(getattr(pal, k))
        self._loading = False
        self.changed()
        self._commit()
        self.statusBar().showMessage(f"Colors taken from {path.name}. Ctrl+Z puts the old ones back.", 8000)

    def _update_title(self) -> None:
        if self.stack.currentIndex() == 0:
            self.setWindowTitle("KDE Customizer")
            return
        name = self.path.name if self.path else "unsaved theme"
        self.setWindowTitle(f"{'• ' if self.dirty else ''}{name} — KDE Customizer")

    # --- AI -----------------------------------------------------------------------------
    def _ai_theme(self, theme: spec.Theme) -> None:
        self._commit()
        self.set_theme(theme, True)
        self._commit()                  # one undo step back to before the AI's version

    # --- file actions -----------------------------------------------------------------
    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(self, "Unsaved changes", "Save changes to this theme first?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def set_theme(self, theme: spec.Theme, dirty: bool) -> None:
        self.theme = theme
        self.to_form()
        self.dirty = dirty
        self._update_title()

    def _fresh(self, theme: spec.Theme, dirty: bool) -> None:
        """A different theme: the undo history starts over."""
        self.set_theme(theme, dirty)
        self._reset_history()
        self.show_editor()

    def new(self) -> None:
        if self._confirm_discard():
            self.path = None
            self._fresh(spec.Theme(name="New Theme", id="org.kdecustomizer.newtheme"), False)

    def from_desktop(self) -> None:
        """New unsaved theme = snapshot of the running desktop."""
        if not self._confirm_discard():
            return
        from .. import snapshot
        try:
            theme = snapshot.take("My Desktop")
        except Exception as e:  # unreadable config: tell the user rather than crash
            QMessageBox.critical(self, "Snapshot failed", str(e))
            return
        self.path = None
        self._fresh(theme, True)
        self.statusBar().showMessage(snapshot.summary(theme).replace("\n", " · "), 10000)

    def load(self, path: Path) -> None:
        try:
            theme = spec.load(path)
        except Exception as e:  # show any parse error to the user
            QMessageBox.critical(self, "Load failed", str(e))
            return
        self.path = path
        self._fresh(theme, False)
        library.add_recent(path)

    def open(self) -> None:
        if not self._confirm_discard():
            return
        start = system.themes_dir()
        f, _ = QFileDialog.getOpenFileName(self, "Open theme", str(start if start.is_dir() else Path.home()),
                                           "Theme spec (*.toml)")
        if f:
            self.load(Path(f))

    def _ask_name(self) -> bool:
        """A theme still called "Untitled" / "New Theme"… gets a real name (and matching id) first."""
        t = self.from_form()
        if not spec.is_placeholder_name(t.name):
            return True
        old_id = t.id
        while True:
            name, ok = QInputDialog.getText(self, "Name your theme",
                                            "What should this theme be called?", text="")
            if not ok:
                return False
            if name.strip() and not spec.is_placeholder_name(name):
                break
        self.text["name"].setText(name.strip())
        if spec.is_placeholder_id(old_id) or old_id == spec.id_for(t.name):
            self.text["id"].setText(spec.id_for(name.strip()))
        self.from_form()
        return True

    def save(self) -> bool:
        """First save of a theme: name it if needed, then into the themes folder — no file dialog."""
        if not self.path:
            if not self._ask_name():
                return False
            while True:
                target = spec.default_path(self.from_form())
                if not target.exists():
                    break
                r = QMessageBox.question(
                    self, "Theme already exists",
                    f"{target.parent} already has a theme called “{self.theme.name}”.\n\n"
                    "Replace it, or give this one another name?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.No)
                if r == QMessageBox.Yes:
                    break
                if r == QMessageBox.Cancel:
                    return False
                self.text["name"].setText("")            # ask again
                if not self._ask_name():
                    return False
            target.parent.mkdir(parents=True, exist_ok=True)
            self.path = target
        return self._write()

    def save_as(self) -> bool:
        if not self._ask_name():
            return False
        start = str(self.path if self.path else spec.default_path(self.from_form()))
        Path(start).parent.mkdir(parents=True, exist_ok=True)
        f, _ = QFileDialog.getSaveFileName(self, "Save theme as", start, "Theme spec (*.toml)")
        if not f:
            return False
        self.path = Path(f)
        return self._write()

    def _write(self) -> bool:
        out = copy.deepcopy(self.from_form())
        for attr in ("wallpaper",):  # keep files next to the spec portable
            val = getattr(out, attr)
            if val:
                try:
                    setattr(out, attr, str(Path(val).resolve().relative_to(self.path.resolve().parent)))
                except ValueError:
                    pass
        if out.iconset.signature_dir:
            try:
                out.iconset.signature_dir = str(Path(out.iconset.signature_dir).resolve()
                                                .relative_to(self.path.resolve().parent))
            except ValueError:
                pass
        spec.save(out, self.path)
        library.add_recent(self.path)
        self.dirty = False
        self._update_title()
        self.statusBar().showMessage(f"Saved {self.path}", 4000)
        return True

    def _build_root(self) -> Path:
        return self.path.parent / "build"

    def do_build(self) -> Path | None:
        if not self.path and not self.save():      # builds live in the theme's own folder
            return None
        try:
            out = builder.build(copy.deepcopy(self.from_form()), self._build_root())
        except Exception as e:
            QMessageBox.critical(self, "Build failed", str(e))
            return None
        self.statusBar().showMessage(f"Built {out}", 6000)
        return out

    def pick_wallpaper(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Choose wallpaper", str(Path.home()),
                                           "Images (*.png *.jpg *.jpeg *.webp *.svg)")
        if f:
            self.text["wallpaper"].setText(f)

    def make_wallpaper(self) -> None:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QInputDialog
        from .. import wallpaper
        from .icons_tab import _Worker
        if getattr(self, "_wp_thread", None):
            return
        idea, ok = QInputDialog.getText(self, "Make wallpaper", "What should it show? (it gets this theme's "
                                        "colors)", text=self.theme.description)
        if not ok or not self._ensure_saved():
            return
        theme = copy.deepcopy(self.from_form())
        it = self.icons_tab
        url, perf, model, folder = it.url.text().strip(), it.perf.currentText().strip(), it._model(), self.path.parent

        def job(log):
            return [str(wallpaper.generate(theme, folder, url, idea=idea, performance=perf, model=model, log=log))]
        self.wp_make.setEnabled(False)
        self._wp_thread = QThread(self)
        self._wp_worker = _Worker(job)
        self._wp_worker.moveToThread(self._wp_thread)
        self._wp_thread.started.connect(self._wp_worker.run)
        # bound methods so Qt runs these on the GUI thread
        self._wp_worker.progress.connect(self._wp_progress)
        self._wp_worker.done.connect(self._wp_done)
        self._wp_worker.failed.connect(self._wp_failed)
        self._wp_thread.start()

    def _wp_progress(self, text: str) -> None:
        self.statusBar().showMessage(text[:1].upper() + text[1:])

    def _wp_stop(self) -> None:
        self.wp_make.setEnabled(True)
        self._wp_thread.quit()
        self._wp_thread.wait()
        self._wp_thread = None

    def _wp_done(self, paths: list) -> None:
        self._wp_stop()
        self.text["wallpaper"].setText(paths[0])
        self.statusBar().showMessage("Wallpaper made. Save, then Apply to use it.", 8000)

    def _wp_failed(self, msg: str) -> None:
        self._wp_stop()
        QMessageBox.warning(self, "Make wallpaper", msg)

    def export(self) -> None:
        if not self.path and not self.save():
            return
        theme = self.from_form()
        f, _ = QFileDialog.getSaveFileName(self, "Export theme", f"{theme.slug}.tar.gz", "Theme archive (*.tar.gz)")
        if not f:
            return
        try:
            dest = builder.export(copy.deepcopy(theme), f, self._build_root())
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        self.statusBar().showMessage(f"Exported {dest} — recipient extracts it and runs ./install.sh", 8000)

    def apply(self) -> None:
        if self.proc.state() != QProcess.NotRunning:
            return
        t = self.theme
        system_parts = [n for on, n in [(t.login_screen.generate, "login screen"),
                                        (t.boot_splash.generate, "boot splash")] if on]
        r = QMessageBox.question(self, "Apply to desktop",
                                 f"Install and apply “{t.name}” to your live desktop now?"
                                 + ("\n\nYour current panels will be replaced." if self.with_layout.isChecked() else "")
                                 + (f"\n\nThe {' and '.join(system_parts)} need your admin password (asked only "
                                    "when they changed)." if system_parts else "")
                                 + "\n\nYou'll have 20 seconds to keep the result or go back.")
        if r != QMessageBox.Yes:
            return
        out = self.do_build()
        if out:
            self.say(f"$ {out / 'install.sh'}")
            dlg = ApplyDialog(self, t.name, out / "install.sh",
                              ["--layout"] if self.with_layout.isChecked() else [], bool(system_parts))
            dlg.output.connect(self.log.appendPlainText)
            dlg.exec()
            self.statusBar().showMessage(dlg.result_text, 8000)

    def revert(self) -> None:
        from .. import restorepoints
        if self.proc.state() != QProcess.NotRunning:
            return
        pts = restorepoints.points()
        if not pts:
            QMessageBox.information(self, "Undo Apply", "There is nothing to undo yet: each Apply saves the desktop "
                                    "as it was first, and that's what Undo Apply restores.")
            return
        pt = pts[0]
        r = QMessageBox.question(self, "Undo Apply",
                                 f"Restore the desktop as it was {pt.label()}?\n\n"
                                 "Colors, styles, icons, cursors, fonts, wallpaper, tweaks and terminal/GTK colors "
                                 "go back. The login screen and boot splash stay as they are.")
        if r != QMessageBox.Yes:
            return

        def done(code: int) -> str:
            if code:
                return f"restore failed (exit {code}) — see Output"
            import shutil
            shutil.rmtree(pt.path, ignore_errors=True)      # the next Undo goes one step further back
            return "Desktop restored."
        self.say(f"$ bash {pt.script}")
        self._proc_done = done
        self.proc.start("bash", [str(pt.script)])

    def closeEvent(self, e) -> None:
        if self._confirm_discard():
            e.accept()
        else:
            e.ignore()


def main() -> int:
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
