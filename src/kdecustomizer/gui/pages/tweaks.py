"""Tweaks section: a File / Group / Key / Value table <-> `theme.tweaks` (any KDE setting written at install
time), with ready-made rows from `fields.TWEAK_PRESETS`."""
from __future__ import annotations


from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout,
    QWidget,
)

from ..fields import _tweak_text, _tweak_value, TWEAK_PRESETS
from . import FormHelpers


class TweaksPage(FormHelpers):
    """The Tweaks section (a mixin of app.Main)."""

    def _tweaks_tab(self) -> QWidget:
        """The settings table with Add / Remove and the preset menu."""
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
