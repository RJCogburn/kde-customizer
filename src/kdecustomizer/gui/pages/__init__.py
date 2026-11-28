"""The editor's sections, one module each (Theme, Colors, Desktop, Panels, Fonts, Tweaks). Each is a mixin of
`app.Main`: it builds its section's form and handles that section's own buttons; the shared state (`self.theme`,
`self.text`, `self.colors`, `self.changed`…) lives in Main. `FormHelpers` = the layout helpers every page uses."""
from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QGroupBox, QLineEdit, QVBoxLayout, QWidget



class FormHelpers:
    """Layout helpers for the section pages."""

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
        """A text field for the Theme attribute `attr`, registered in self.text (to_form/from_form use it)."""
        w = QLineEdit(placeholderText=placeholder)
        w.textChanged.connect(self.changed)
        form.addRow(label, w)
        self.text[attr] = w
        return w
