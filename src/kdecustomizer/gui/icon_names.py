"""Icons › Icon names: what each icon name is for, what your theme shows for it now, and your own file for it.

Icon themes are folders of files named after what they show (`folder-music.svg`); apps ask for the name. This
window lists the names people usually want to change (iconnames.CATALOG), every app on this computer, and every
name the base theme has, with a search box. "Use my image…" copies an SVG/PNG into the theme's own-icons folder
under the right name."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QMessageBox, QPushButton, QSplitter, QTableView, QVBoxLayout, QWidget,
)

from .. import iconnames

ALL = "All common names"
APPS = "Apps on this computer"
MINE = "Your icons"


def everything(base: str) -> str:
    return f"Everything in {base}"


class NamesModel(QAbstractTableModel):
    """Rows of (name, what it's for) with the theme's icon and the user's own one as decorations."""

    HEADERS = ["Now", "Yours", "Name", "What it's for"]

    def __init__(self):
        super().__init__()
        self.rows: list[tuple[str, str]] = []
        self.index_: dict[str, iconnames.Entry] = {}
        self.mine: dict[str, Path] = {}
        self._icons: dict[str, QIcon] = {}

    def set_rows(self, rows, index, mine) -> None:
        self.beginResetModel()
        self.rows, self.index_, self.mine = rows, index, mine
        self._icons.clear()
        self.endResetModel()

    def set_mine(self, mine: dict[str, Path]) -> None:
        self.mine = mine
        self._icons = {k: v for k, v in self._icons.items() if not k.startswith("mine:")}
        if self.rows:
            self.dataChanged.emit(self.index(0, 1), self.index(len(self.rows) - 1, 1))

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else 4

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return None

    def _icon(self, key: str, path: Path | None) -> QIcon | None:
        if path is None:
            return None
        if key not in self._icons:
            self._icons[key] = QIcon(str(path))
        return self._icons[key]

    def data(self, index, role=Qt.DisplayRole):
        """Columns: theme's icon, your icon, name, purpose; icons are loaded when a row is shown."""
        if not index.isValid():
            return None
        name, purpose = self.rows[index.row()]
        col = index.column()
        if role == Qt.DecorationRole:
            if col == 0:
                e = self.index_.get(name)
                return self._icon(name, e.path if e else None)
            if col == 1:
                return self._icon("mine:" + name, self.mine.get(name))
        elif role == Qt.DisplayRole:
            if col == 2:
                return name
            if col == 3:
                return purpose
        elif role == Qt.ToolTipRole:
            e = self.index_.get(name)
            if col == 0:
                return str(e.path) if e else "the base theme has no icon with this name"
            if col == 1:
                return str(self.mine[name]) if name in self.mine else "not set: the theme's icon is used"
            return f"{name}\n{purpose}"
        elif role == Qt.UserRole:
            return name
        return None


class IconNamesDialog(QDialog):
    """Browse icon names by category or search, and set your own file for one."""

    icons_changed = Signal()        # a file in the own-icons folder was added or removed

    def __init__(self, parent, base: str, get_folder):
        """`get_folder(create)`: the theme's own-icons folder (None if it has none yet and `create` is False, or it
        can't have one: an unsaved theme)."""
        super().__init__(parent)
        self.setWindowTitle("Icon Names")
        self.resize(980, 640)
        self.base, self.get_folder = base, get_folder
        self.index_ = iconnames.theme_index(base)
        self.apps = iconnames.installed_apps()
        v = QVBoxLayout(self)
        intro = QLabel("An icon theme is a folder of files named after what they show. Apps ask for a <b>name</b> "
                       "(not a file): to change an icon, give your SVG or PNG that exact name, e.g. "
                       "<code>folder-music.svg</code>. Pick a name below and use <b>Use my image…</b>, or put "
                       "files named like this in your folder yourself. Names you don't set keep the theme's icon. "
                       "SVG stays sharp at every size; PNGs should be square, 256 px or more.")
        intro.setWordWrap(True)
        v.addWidget(intro)

        split = QSplitter()
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.cats = QListWidget()
        for c in [ALL, *iconnames.CONTEXTS, APPS, everything(base), MINE]:
            self.cats.addItem(c)
        self.cats.currentTextChanged.connect(self._category)
        lv.addWidget(self.cats, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: palette(placeholder-text);")
        lv.addWidget(self.note)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit(placeholderText="Search names and descriptions, e.g. trash, music, wifi…")
        self.search.setClearButtonEnabled(True)
        rv.addWidget(self.search)
        self.model = NamesModel()
        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.search.textChanged.connect(self._filter)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setIconSize(QSize(32, 32))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(-1, Qt.AscendingOrder)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        h.setSectionResizeMode(1, QHeaderView.Fixed)
        h.resizeSection(0, 52)
        h.resizeSection(1, 52)
        h.setSectionResizeMode(2, QHeaderView.Interactive)
        h.resizeSection(2, 260)
        h.setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _i: self.use_image())
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._enable())
        rv.addWidget(self.table, 1)
        self.count = QLabel()
        rv.addWidget(self.count)
        split.addWidget(right)
        split.setSizes([220, 760])
        v.addWidget(split, 1)

        row = QHBoxLayout()
        self.use_btn = QPushButton(QIcon.fromTheme("document-open"), "Use my image…")
        self.use_btn.setToolTip("Pick an SVG or PNG for the selected name (copied into your icons folder)")
        self.use_btn.clicked.connect(self.use_image)
        self.remove_btn = QPushButton(QIcon.fromTheme("edit-delete"), "Remove mine")
        self.remove_btn.setToolTip("Delete your file for this name: the theme's icon is used again")
        self.remove_btn.clicked.connect(self.remove_mine)
        self.copy_btn = QPushButton(QIcon.fromTheme("edit-copy"), "Copy name")
        self.copy_btn.clicked.connect(self.copy_name)
        self.folder_btn = QPushButton(QIcon.fromTheme("folder-open"), "Open my folder")
        self.folder_btn.setToolTip("Your icons folder, to add or edit files directly")
        self.folder_btn.clicked.connect(self.open_folder)
        for b in (self.use_btn, self.remove_btn, self.copy_btn, self.folder_btn):
            row.addWidget(b)
        row.addStretch()
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        row.addWidget(box)
        v.addLayout(row)
        self.cats.setCurrentRow(0)

    # --- lists --------------------------------------------------------------------
    def _mine(self) -> dict[str, Path]:
        return iconnames.custom_icons(self.get_folder(False))

    def _rows(self, cat: str) -> list[tuple[str, str]]:
        """The (name, description) rows for a category."""
        mine = self._mine()
        if cat == ALL:
            return [(n, f"{p}  ·  {c}") for n, c, p in iconnames.CATALOG]
        if cat in iconnames.CONTEXTS:
            return [(n, p) for n, c, p in iconnames.CATALOG if c == cat]
        if cat == APPS:
            return [(icon, app) for icon, app in self.apps.items()]
        if cat == MINE:
            return [(n, iconnames.PURPOSE.get(n) or self.apps.get(n) or
                     ("" if n in self.index_ else "⚠ nothing asks for this name — check the spelling"))
                    for n in sorted(mine)]
        return [(n, iconnames.PURPOSE.get(n) or self.apps.get(n) or e.context)
                for n, e in sorted(self.index_.items())]

    def _category(self, cat: str) -> None:
        self.model.set_rows(self._rows(cat), self.index_, self._mine())
        self.note.setText(iconnames.NOTES.get(cat, {
            ALL: "The names people most often change. Pick a category for what each one is used for.",
            APPS: "Every app in your launcher, by the icon name its .desktop file asks for.",
            MINE: "The files in your icons folder.",
        }.get(cat, f"Every icon name {self.base} (and the themes it builds on) has.")))
        self._filter(self.search.text())

    def _filter(self, text: str) -> None:
        self.proxy.setFilterFixedString(text.strip())
        n = self.proxy.rowCount()
        self.count.setText(f"{n} name{'s' if n != 1 else ''}")
        self._enable()

    def _selected(self) -> str | None:
        rows = self.table.selectionModel().selectedRows(2)
        return rows[0].data(Qt.UserRole) if rows else None

    def _enable(self) -> None:
        name = self._selected()
        self.use_btn.setEnabled(bool(name))
        self.copy_btn.setEnabled(bool(name))
        self.remove_btn.setEnabled(bool(name) and name in self.model.mine)

    def select(self, name: str) -> None:
        """Show a name (searching for it)."""
        self.search.setText(name)
        for r in range(self.proxy.rowCount()):
            if self.proxy.index(r, 2).data() == name:
                self.table.selectRow(r)
                break

    # --- actions ------------------------------------------------------------------
    def use_image(self) -> None:
        """Pick an SVG/PNG for the selected name; it's copied into the own-icons folder (made if needed)."""
        name = self._selected()
        if not name:
            return
        folder = self.get_folder(True)
        if folder is None:
            return
        f, _ = QFileDialog.getOpenFileName(self, f"Your icon for “{name}”", str(Path.home()),
                                           "Icons (*.svg *.png)")
        if not f:
            return
        try:
            iconnames.add_custom(folder, name, f)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Use my image", str(e))
            return
        self._refresh_mine()

    def remove_mine(self) -> None:
        name = self._selected()
        folder = self.get_folder(False)
        if name and folder:
            iconnames.remove_custom(folder, name)
            self._refresh_mine()

    def _refresh_mine(self) -> None:
        if self.cats.currentItem() and self.cats.currentItem().text() == MINE:
            self._category(MINE)
        else:
            self.model.set_mine(self._mine())
        self._enable()
        self.icons_changed.emit()

    def copy_name(self) -> None:
        if name := self._selected():
            QGuiApplication.clipboard().setText(name)

    def open_folder(self) -> None:
        folder = self.get_folder(True)
        if folder is not None:
            subprocess.Popen(["xdg-open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
