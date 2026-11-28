"""Fonts section: one font field per KDE font role (empty = leave as is)."""
from __future__ import annotations

from dataclasses import fields

from PySide6.QtWidgets import QWidget

from ... import spec
from ..fields import FontField, scroll
from . import FormHelpers


class FontsPage(FormHelpers):
    """The Fonts section (a mixin of app.Main)."""

    def _fonts_tab(self) -> QWidget:
        """One font field per KDE font role."""
        page, v = self._form_page()
        f = self._group("Fonts", v)
        self.fonts: dict[str, FontField] = {}
        for fld in fields(spec.Fonts):
            ff = FontField()
            ff.changed.connect(self.changed)
            self.fonts[fld.name] = ff
            f.addRow(fld.name.replace("_", " ").capitalize(), ff)
        v.addStretch()
        return scroll(page)
