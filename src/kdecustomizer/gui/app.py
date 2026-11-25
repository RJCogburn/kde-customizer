"""kdec-gui — theme editor with live preview. Thin layer over spec/build; no theme logic here."""
from __future__ import annotations

import copy
import sys
from dataclasses import fields
from pathlib import Path

from PySide6.QtCore import QProcess, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox, QDockWidget, QFileDialog,
    QFontDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QHeaderView, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from .. import build as builder
from .. import color, spec, system
from .. import cursorset, iconset
from .ai_panel import AIPanel
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

# "Add common" tweaks: (menu label, [(file, group, key, value)])
TWEAK_PRESETS = [
    ("Wobbly windows", [("kwinrc", "Plugins", "wobblywindowsEnabled", True)]),
    ("Magic lamp minimize", [("kwinrc", "Plugins", "magiclampEnabled", True),
                             ("kwinrc", "Plugins", "squashEnabled", False)]),
    ("Dim inactive windows", [("kwinrc", "Plugins", "diminactiveEnabled", True)]),
    ("Shake cursor to find it", [("kwinrc", "Plugins", "shakecursorEnabled", True)]),
    ("Stronger blur", [("kwinrc", "Plugins", "blurEnabled", True), ("kwinrc", "Effect-blur", "BlurStrength", 10)]),
    ("Faster animations", [("kdeglobals", "KDE", "AnimationDurationFactor", 0.5)]),
    ("Single click opens files", [("kdeglobals", "KDE", "SingleClick", True)]),
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
        self.ai.undo.clicked.connect(self._undo_ai)
        self._history: list[spec.Theme] = []

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        lv.addWidget(self.ai)
        line = QFrame(frameShape=QFrame.HLine, frameShadow=QFrame.Sunken)
        lv.addWidget(line)
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
        self.setCentralWidget(split)

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

        if path:
            self.load(Path(path))
        else:
            self.to_form()
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

        act("New", "document-new", self.new, QKeySequence.New)
        act("Open…", "document-open", self.open, QKeySequence.Open)
        act("From Desktop", "camera-photo", self.from_desktop, None,
            "Start a theme from your current desktop: colors, styles, fonts, panels and wallpaper")
        act("Save", "document-save", self.save, QKeySequence.Save)
        tb.addSeparator()
        act("Build", "run-build", self.do_build, "Ctrl+B", "Write theme files to build/")
        act("Export…", "document-export", self.export, "Ctrl+E", "Pack a shareable .tar.gz with the wallpaper")
        tb.addSeparator()
        self.with_layout = QCheckBox("Replace panels")
        self.with_layout.setToolTip("Also replace your current panels with the theme's panel layout")
        tb.addWidget(self.with_layout)
        apply = act("Apply to desktop", "dialog-ok-apply", self.apply, "Ctrl+Return",
                    "Build, install and apply to your live desktop")
        f = apply.font()
        f.setBold(True)
        apply.setFont(f)

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
        self.proc.finished.connect(lambda code, _s: self.statusBar().showMessage(
            "Applied." if code == 0 else f"install.sh failed (exit {code}) — see Output", 6000))

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
        row.addWidget(self.text["wallpaper"])
        row.addWidget(browse)
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

        f = self._group("Login screen", v)
        self.l_generate = QCheckBox("Theme the login screen")
        self.l_generate.setToolTip("Colors, Plasma style, icons, cursors and wallpaper on the Plasma Login "
                                   "screen. Installing asks for the admin password (only when it changed).")
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
        for label, entries in TWEAK_PRESETS:
            menu.addAction(label, lambda e=entries: self._add_tweaks(e))
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
        self._after_change()

    def _after_change(self) -> None:
        self._refresh.start()
        self._update_contrast()
        ics = self.theme.iconset
        key = (ics.generate, ics.base, ics.signature_dir, self.theme.palette.accent, self.theme.slug)
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
        self._icons_key = (ics.generate, ics.base, ics.signature_dir, t.palette.accent, t.slug)
        paths = [p for p in QIcon.themeSearchPaths() if p != str(root)]
        QIcon.setThemeSearchPaths([str(root), *paths])  # also makes Qt drop its cached lookups
        self.preview.icons.clear()
        self.preview.update()

    def _ensure_saved(self) -> bool:
        """Signature icons are stored next to the spec, so it needs a file first."""
        if self.path and not self.dirty:
            return True
        if not self.path:
            QMessageBox.information(self, "Save the theme first",
                                    "Signature icons are kept in a folder next to the theme file. "
                                    "Choose where to save the theme.")
        return self.save()

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

    def _update_title(self) -> None:
        name = self.path.name if self.path else "unsaved theme"
        self.setWindowTitle(f"{'• ' if self.dirty else ''}{name} — KDE Customizer")

    # --- AI -----------------------------------------------------------------------------
    def _ai_theme(self, theme: spec.Theme) -> None:
        self._history.append(copy.deepcopy(self.from_form()))
        self.ai.undo.setEnabled(True)
        self.set_theme(theme, True)

    def _undo_ai(self) -> None:
        if self._history:
            self.set_theme(self._history.pop(), True)
        self.ai.undo.setEnabled(bool(self._history))

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

    def new(self) -> None:
        if self._confirm_discard():
            self.path = None
            self.set_theme(spec.Theme(name="New Theme", id="org.kdecustomizer.newtheme"), False)

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
        self.set_theme(theme, True)
        self.statusBar().showMessage(snapshot.summary(theme).replace("\n", " · "), 10000)

    def load(self, path: Path) -> None:
        try:
            theme = spec.load(path)
        except Exception as e:  # show any parse error to the user
            QMessageBox.critical(self, "Load failed", str(e))
            return
        self.path = path
        self.set_theme(theme, False)

    def open(self) -> None:
        if not self._confirm_discard():
            return
        f, _ = QFileDialog.getOpenFileName(self, "Open theme", "", "Theme spec (*.toml)")
        if f:
            self.load(Path(f))

    def save(self) -> bool:
        if not self.path:
            f, _ = QFileDialog.getSaveFileName(self, "Save theme", f"{self.theme.slug.lower()}.toml",
                                               "Theme spec (*.toml)")
            if not f:
                return False
            self.path = Path(f)
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
        self.dirty = False
        self._update_title()
        self.statusBar().showMessage(f"Saved {self.path}", 4000)
        return True

    def _build_root(self) -> Path:
        return (self.path.parent if self.path else Path.cwd()) / "build"

    def do_build(self) -> Path | None:
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

    def export(self) -> None:
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
        r = QMessageBox.question(self, "Apply to desktop",
                                 f"Install and apply “{self.theme.name}” to your live desktop now?"
                                 + ("\n\nYour current panels will be replaced." if self.with_layout.isChecked() else ""))
        if r != QMessageBox.Yes:
            return
        out = self.do_build()
        if out:
            self.say(f"$ {out / 'install.sh'}")
            self.proc.start(str(out / "install.sh"), ["--layout"] if self.with_layout.isChecked() else [])

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
