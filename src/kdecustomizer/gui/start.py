"""Start page: recent themes and the built-in starting points as preview cards, plus New / From Desktop / Open."""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QDateTime, QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QMenu, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from .. import __version__, installed, library, spec
from .preview import Preview

THUMB = QSize(256, 160)
_cache: dict[tuple[str, float], QPixmap] = {}       # (spec path, mtime) -> thumbnail


def thumbnail(path: Path, renderer: Preview) -> QPixmap:
    """The editor's preview of a spec, small. Cached per file version."""
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        return QPixmap()
    if key not in _cache:
        renderer.show_theme(spec.load(path))
        _cache[key] = renderer.grab().scaled(THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return _cache[key]


class Cards(QListWidget):
    """A wrapping grid of theme cards; each item's data is its spec path."""

    MIN_CELL = THUMB.width() + 24

    def __init__(self):
        super().__init__()
        self.setViewMode(QListView.IconMode)
        self.setIconSize(THUMB)
        self.setGridSize(QSize(self.MIN_CELL, self.cell_height()))
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setWrapping(True)
        self.setWordWrap(True)
        self.setFrameShape(QListWidget.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QListWidget { background: transparent; }")

    def item_height(self) -> int:
        """Thumbnail + one line of name + the view's item margins."""
        return THUMB.height() + self.fontMetrics().lineSpacing() + 12

    def cell_height(self) -> int:
        return self.item_height() + 8

    def fit(self) -> None:
        """Spread the columns over the full width and grow to show every row (the page scrolls, not each grid)."""
        if not self.count():
            self.setFixedHeight(0)
            return
        width = self.viewport().width() - 4         # cells that fill the width exactly wrap one too early
        per_row = max(1, width // self.MIN_CELL)
        cell = QSize(max(self.MIN_CELL, width // per_row), self.cell_height())
        if cell != self.gridSize():
            self.setGridSize(cell)
        rows = -(-self.count() // per_row)
        # the last row needs no gap below it
        self.setFixedHeight(rows * cell.height() - (cell.height() - self.item_height()) + 2)

    def keyPressEvent(self, e) -> None:
        """Enter opens the selected card (clicks open too; itemActivated would fire twice with single-click)."""
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.currentItem():
            self.itemClicked.emit(self.currentItem())
        else:
            super().keyPressEvent(e)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.fit()


class StartPage(QWidget):
    """Recent themes and starting points as preview cards, plus the start actions and banners."""

    new_theme = Signal()
    from_desktop = Signal()
    from_image = Signal()            # a new theme in the colors of a picture, with it as the wallpaper
    open_file = Signal()
    open_path = Signal(str)          # a recent theme
    open_starter = Signal(str)       # a built-in starting point (opens as a new, unsaved theme)
    manage = Signal()
    recover = Signal()               # unsaved changes kept from last time
    discard_recovery = Signal()
    setup_check = Signal()
    install_shared = Signal()        # a theme someone exported (.tar.gz)

    def __init__(self):
        super().__init__()
        self._renderer = Preview()
        self._renderer.resize(640, 400)
        self._todo: list[QListWidgetItem] = []
        self._timer = QTimer(self, interval=0)
        self._timer.timeout.connect(self._render_next)

        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(32, 24, 32, 24)
        v.setSpacing(10)
        title = QLabel("KDE Customizer")
        f = QFont(title.font())
        f.setPointSizeF(f.pointSizeF() * 1.8)
        f.setBold(True)
        title.setFont(f)
        v.addWidget(title)
        sub = QLabel("Make a complete Plasma theme (colors, panels, icons, cursors, title bars, login screen and "
                     "more) from one set of colors. Start from one of these, or from scratch.")
        sub.setWordWrap(True)
        v.addWidget(sub)

        # unsaved changes from last time (the app was closed without saving, or crashed)
        self.recovery = QFrame()
        self.recovery.setObjectName("recovery")
        self.recovery.setStyleSheet("#recovery { background: rgba(61, 174, 233, 0.14); border: 1px solid "
                                    "rgba(61, 174, 233, 0.6); border-radius: 6px; }")
        rh = QHBoxLayout(self.recovery)
        rh.setContentsMargins(10, 6, 6, 6)
        icon = QLabel()
        icon.setPixmap(QIcon.fromTheme("document-revert").pixmap(22, 22))
        rh.addWidget(icon)
        self.recovery_text = QLabel()
        self.recovery_text.setWordWrap(True)
        rh.addWidget(self.recovery_text, 1)
        b = QPushButton(QIcon.fromTheme("document-open-recent"), "Recover")
        b.clicked.connect(self.recover)
        rh.addWidget(b)
        b = QPushButton(QIcon.fromTheme("edit-delete"), "Discard")
        b.setToolTip("Throw these changes away")
        b.clicked.connect(self.discard_recovery)
        rh.addWidget(b)
        v.addWidget(self.recovery)

        # a newer release (AppImage / tarball only: see updates.py)
        self.update_bar = QFrame()
        self.update_bar.setObjectName("update")
        self.update_bar.setStyleSheet("#update { background: rgba(39, 174, 96, 0.14); border: 1px solid "
                                      "rgba(39, 174, 96, 0.6); border-radius: 6px; }")
        uh = QHBoxLayout(self.update_bar)
        uh.setContentsMargins(10, 6, 6, 6)
        icon = QLabel()
        icon.setPixmap(QIcon.fromTheme("update-none", QIcon.fromTheme("system-software-update")).pixmap(22, 22))
        uh.addWidget(icon)
        self.update_text = QLabel()
        self.update_text.setWordWrap(True)
        uh.addWidget(self.update_text, 1)
        self.update_url = ""
        b = QPushButton(QIcon.fromTheme("download"), "Download")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.update_url)))
        uh.addWidget(b)
        b = QPushButton("Not now")
        b.clicked.connect(self.update_bar.hide)
        uh.addWidget(b)
        b = QPushButton("Don't check")
        b.setToolTip("Stop looking for new versions (no more requests to GitHub)")
        b.clicked.connect(self._no_updates)
        uh.addWidget(b)
        self.update_bar.hide()
        v.addWidget(self.update_bar)

        row = QHBoxLayout()
        for text, icon, sig, tip in [
            ("New theme", "document-new", self.new_theme, "Start from the default colors"),
            ("From my desktop", "camera-photo", self.from_desktop,
             "Start from what your desktop looks like now: colors, styles, fonts, panels and wallpaper"),
            ("From a picture…", "viewimage", self.from_image,
             "Pick an image (a photo, artwork, a wallpaper): the theme takes its colors and uses it as the wallpaper"),
            ("Open…", "document-open", self.open_file,
             "Open a theme file (.toml) — or drop one, or a shared .tar.gz, on this window"),
            ("Install a shared theme…", "document-import", self.install_shared,
             "Install a theme someone exported for you (.tar.gz)"),
            ("Installed themes…", "preferences-desktop-theme-global", self.manage,
             "See and remove the themes kde-customizer has installed"),
            ("Setup check", "tools-report-bug", self.setup_check,
             "Which optional parts work on this computer, and how to install the ones that don't"),
        ]:
            b = QPushButton(QIcon.fromTheme(icon), text)
            b.setToolTip(tip)
            b.clicked.connect(sig)
            row.addWidget(b)
            if sig is self.manage:
                self.manage_btn = b
        row.addStretch()
        v.addLayout(row)

        self.recent_label = self._heading("Recent themes", v)
        self.recent = Cards()
        self.recent.itemClicked.connect(lambda it: self.open_path.emit(it.data(Qt.UserRole)))
        self.recent.setContextMenuPolicy(Qt.CustomContextMenu)
        self.recent.customContextMenuRequested.connect(self._recent_menu)
        v.addWidget(self.recent)

        self._heading("Starting points", v)
        self.starters = Cards()
        self.starters.itemClicked.connect(lambda it: self.open_starter.emit(it.data(Qt.UserRole)))
        v.addWidget(self.starters)
        v.addStretch()

        area = QScrollArea()
        area.setWidget(inner)
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(area)
        self.refresh()

    def show_update(self, version: str, url: str) -> None:
        self.update_url = url
        self.update_text.setText(f"<b>KDE Customizer {html.escape(version)} is out</b> (you have "
                                 f"{html.escape(__version__)}). Download it and replace this one; your themes and "
                                 "settings stay.")
        self.update_bar.show()

    def _no_updates(self) -> None:
        QSettings("kdecustomizer", "kdec-gui").setValue("updates/check", False)
        self.update_bar.hide()

    def _heading(self, text: str, v: QVBoxLayout) -> QLabel:
        lbl = QLabel(text)
        f = QFont(lbl.font())
        f.setPointSizeF(f.pointSizeF() * 1.2)
        f.setBold(True)
        lbl.setFont(f)
        v.addSpacing(8)
        v.addWidget(lbl)
        return lbl

    def refresh(self, recovery: bool = True) -> None:
        """Re-read the recent list and kept changes (the starters never change). `recovery`=False: the kept changes
        are the editor's own, still open."""
        kept = library.autosaved() if recovery else None
        if kept:
            _, path, name, when = kept
            stamp = QDateTime.fromSecsSinceEpoch(int(when)).toString("ddd d MMM, hh:mm")
            where = f" ({path.name})" if path else " (never saved)"
            self.recovery_text.setText(f"<b>Unsaved changes to “{html.escape(name)}”</b>{html.escape(where)} were "
                                       f"kept from {stamp}.")
        self.recovery.setVisible(bool(kept))
        try:
            changed = len(installed.outdated())
        except Exception:       # unreadable state: just no hint
            changed = 0
        self.manage_btn.setText("Installed themes…" + (f" ({changed} changed)" if changed else ""))
        self.manage_btn.setToolTip("See and remove the themes kde-customizer has installed" + (
            f"\n{changed} of them changed in their theme file since they were installed: Update applies them "
            "again" if changed else ""))
        self._fill(self.recent, library.recent(), lambda p, t: t.name, lambda p, t: str(p))
        has = self.recent.count() > 0
        self.recent_label.setVisible(has)
        self.recent.setVisible(has)
        if not self.starters.count():
            self._fill(self.starters, library.starters(), lambda p, t: t.name, lambda p, t: t.description)
        self._timer.start()

    def _fill(self, grid: Cards, paths: list[Path], label, tip) -> None:
        # forget this grid's pending thumbnails first: clear() deletes the C++ items under the Python wrappers
        """Cards for these spec files; thumbnails are rendered later, one per event-loop turn."""
        self._todo = [it for it in self._todo if it.listWidget() is not grid]
        grid.clear()
        for p in paths:
            try:
                t = spec.load(p)
            except Exception:       # a broken recent file: just leave it out
                continue
            it = QListWidgetItem(label(p, t))
            it.setData(Qt.UserRole, str(p))
            it.setToolTip(tip(p, t))
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            it.setSizeHint(QSize(THUMB.width() + 16, grid.item_height()))   # thumbnails arrive later
            grid.addItem(it)
            self._todo.append(it)
        grid.fit()

    def _render_next(self) -> None:
        """One thumbnail per event-loop turn, so the page shows at once and fills in."""
        while self._todo:
            it = self._todo.pop(0)
            try:
                it.setIcon(QIcon(thumbnail(Path(it.data(Qt.UserRole)), self._renderer)))
            except Exception:
                pass
            return
        self._timer.stop()

    def _recent_menu(self, pos) -> None:
        it = self.recent.itemAt(pos)
        if not it:
            return
        m = QMenu(self)
        m.addAction(QIcon.fromTheme("document-open"), "Open", lambda: self.open_path.emit(it.data(Qt.UserRole)))
        m.addAction(QIcon.fromTheme("list-remove"), "Remove from this list",
                    lambda: (library.remove_recent(it.data(Qt.UserRole)), self.refresh()))
        m.exec(self.recent.viewport().mapToGlobal(pos))
