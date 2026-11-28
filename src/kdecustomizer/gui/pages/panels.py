"""Panels section: the panel list and the selected panel's settings and widgets. Edits are written straight
into `self.theme.panels` (not through from_form)."""
from __future__ import annotations


from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from ... import spec
from ..fields import combo, COMMON_WIDGETS, scroll
from . import FormHelpers


class PanelsPage(FormHelpers):
    """The Panels section (a mixin of app.Main)."""

    def _panels_tab(self) -> QWidget:
        """Panel list, the selected panel's settings, and its widget list."""
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

    def _panel_label(self, p: spec.Panel) -> str:
        return f"{p.location.title()} panel · {p.height}px{' · floating' if p.floating else ''}"

    def _fill_panel_list(self, select: int = 0) -> None:
        """List the theme's panels and select one."""
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
        """Show the selected panel's settings and widgets."""
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
        """Write the panel fields back into the selected panel."""
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
