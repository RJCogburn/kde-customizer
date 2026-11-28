"""Theme section: name, id, author, description, version."""
from __future__ import annotations


from PySide6.QtWidgets import QComboBox, QLineEdit, QPlainTextEdit, QWidget

from ..fields import scroll
from . import FormHelpers


class ThemePage(FormHelpers):
    """The Theme section (a mixin of app.Main)."""

    def _theme_tab(self) -> QWidget:
        """Name, id, author, description and version."""
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
