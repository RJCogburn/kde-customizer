"""Undo Apply › Earlier versions: every restore point (one is taken before each Apply), newest first. Picking one
puts the desktop back as it was right before that Apply."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QVBoxLayout

from .. import restorepoints


def describe(point: restorepoints.Point, newest: bool) -> str:
    when = point.when.strftime("%A %d %B, %H:%M") if point.when else point.path.name
    return f"{when} — before {point.theme} was applied" + ("  (the last Apply)" if newest else "")


class HistoryDialog(QDialog):
    """Every restore point, newest first; `chosen` is the one to restore."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Restore an Earlier Desktop")
        self.resize(560, 380)
        self.chosen: restorepoints.Point | None = None
        v = QVBoxLayout(self)
        intro = QLabel("Each Apply first saves how the desktop looked. Pick a moment to go back to it: colors, styles, "
                       "icons, cursors, fonts, wallpaper, tweaks and terminal/GTK colors return to what they were "
                       "then. The login screen and boot splash stay as they are. The newest 10 are kept.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        self.list = QListWidget()
        self.points = restorepoints.points()
        for i, pt in enumerate(self.points):
            it = QListWidgetItem(QIcon.fromTheme("document-revert"), describe(pt, i == 0))
            it.setData(Qt.UserRole, i)
            self.list.addItem(it)
        if not self.points:
            self.list.addItem("Nothing yet: restore points are made when you Apply a theme.")
            self.list.setEnabled(False)
        v.addWidget(self.list, 1)
        self.box = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.restore = self.box.addButton("Restore this desktop", QDialogButtonBox.AcceptRole)
        self.restore.setIcon(QIcon.fromTheme("document-revert"))
        self.restore.setEnabled(False)
        self.box.accepted.connect(self._accept)
        self.box.rejected.connect(self.reject)
        self.list.currentRowChanged.connect(lambda r: self.restore.setEnabled(bool(self.points) and r >= 0))
        self.list.itemDoubleClicked.connect(lambda _it: self._accept())
        v.addWidget(self.box)
        if self.points:
            self.list.setCurrentRow(0)

    def _accept(self) -> None:
        it = self.list.currentItem()
        if it is None or not self.points:
            return
        self.chosen = self.points[it.data(Qt.UserRole)]
        self.accept()
