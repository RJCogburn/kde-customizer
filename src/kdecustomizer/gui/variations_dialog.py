"""Colors › Variations: nearby palettes drawn as small previews of the whole desktop; click one to use it.
The window opens at once with empty cards; the previews are drawn one per event-loop turn."""
from __future__ import annotations

import copy

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListView, QListWidget, QListWidgetItem, QVBoxLayout

from .. import spec, variations
from .preview import Preview

THUMB = QSize(240, 150)


class VariationsDialog(QDialog):
    """Nearby palettes as small desktop previews; `chosen` is the clicked one."""

    def __init__(self, parent, theme: spec.Theme):
        super().__init__(parent)
        self.setWindowTitle("Color Variations")
        self.chosen: spec.Palette | None = None
        self.options = variations.variations(theme.palette)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Palettes close to this one — all readable. Click one to use it (Ctrl+Z goes back)."))
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setIconSize(THUMB)
        self.grid.setGridSize(QSize(THUMB.width() + 20, THUMB.height() + 36))
        self.grid.setMovement(QListView.Static)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setWrapping(True)
        self.grid.setWordWrap(True)
        self.theme = theme
        self.renderer = Preview()
        self.renderer.resize(640, 400)
        blank = QPixmap(THUMB)
        blank.fill(QColor(128, 128, 128, 40))
        for label, _pal in self.options:
            it = QListWidgetItem(QIcon(blank), label)
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            it.setSizeHint(QSize(THUMB.width() + 12, THUMB.height() + 30))
            self.grid.addItem(it)
        self._next = 0
        self._timer = QTimer(self, interval=0)
        self._timer.timeout.connect(self._render_next)
        self._timer.start()
        self.grid.itemClicked.connect(self._pick)
        self.grid.itemActivated.connect(self._pick)
        v.addWidget(self.grid, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        cols = 3
        self.resize(cols * (THUMB.width() + 20) + 48, -(-len(self.options) // cols) * (THUMB.height() + 36) + 110)

    def _render_next(self) -> None:
        """Draw the next preview (one per event-loop turn, so the window is usable at once)."""
        if self._next >= len(self.options):
            self._timer.stop()
            return
        t = copy.deepcopy(self.theme)
        t.palette = self.options[self._next][1]
        self.renderer.show_theme(t)
        pix = self.renderer.grab().scaled(THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.grid.item(self._next).setIcon(QIcon(pix))
        self._next += 1

    def _pick(self, item: QListWidgetItem) -> None:
        self.chosen = self.options[self.grid.row(item)][1]
        self.accept()
