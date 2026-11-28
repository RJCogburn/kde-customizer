"""Small widgets and constants shared by the editor sections: color and font fields, the Tweaks presets,
the panel widget list, the preview popups, and layout helpers (`combo`, `scroll`)."""
from __future__ import annotations


from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QFontDialog, QHBoxLayout, QLineEdit, QPushButton, QScrollArea, QWidget,
)

from .. import color

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
        """Choose with the font dialog; stored as 'Family,size'."""
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
    ("Desktop", "Scrollbar click jumps to the spot",
     [("kdeglobals", "KDE", "ScrollbarLeftClickNavigatesByPage", False)]),
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
