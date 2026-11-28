"""Colors › Variations: nearby palettes drawn as small previews of the whole desktop; click one to use it."""
from __future__ import annotations

import copy

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListView, QListWidget, QListWidgetItem, QVBoxLayout

from .. import spec, variations
from .preview import Preview

THUMB = QSize(240, 150)


class VariationsDialog(QDialog):
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
        renderer = Preview()
        renderer.resize(640, 400)
        for label, pal in self.options:
            t = copy.deepcopy(theme)
            t.palette = pal
            renderer.show_theme(t)
            it = QListWidgetItem(QIcon(renderer.grab().scaled(THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)),
                                 label)
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            it.setSizeHint(QSize(THUMB.width() + 12, THUMB.height() + 30))
            self.grid.addItem(it)
        self.grid.itemClicked.connect(self._pick)
        self.grid.itemActivated.connect(self._pick)
        v.addWidget(self.grid, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        cols = 3
        self.resize(cols * (THUMB.width() + 20) + 48, -(-len(self.options) // cols) * (THUMB.height() + 36) + 110)

    def _pick(self, item: QListWidgetItem) -> None:
        self.chosen = self.options[self.grid.row(item)][1]
        self.accept()
