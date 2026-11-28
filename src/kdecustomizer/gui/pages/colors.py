"""Colors section: the palette fields with contrast hints, colors from an image, and Variations."""
from __future__ import annotations

import copy
from dataclasses import fields
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QActionGroup, QIcon
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton, QToolButton, QWidget,
)

from ... import color, spec
from ..fields import ColorField, scroll
from . import FormHelpers


class ColorsPage(FormHelpers):
    """The Colors section (a mixin of app.Main)."""

    def _colors_tab(self) -> QWidget:
        """Palette fields, contrast hints, colors from an image, Variations."""
        page, v = self._form_page()
        f = self._group("Palette", v)
        self.colors: dict[str, ColorField] = {}
        hints = {
            "background": "Windows, panels", "surface": "Title bars, buttons, headers",
            "foreground": "Text", "accent": "Selection, focus, highlights",
            "positive": "Success", "neutral": "Warnings", "negative": "Errors, close button",
        }
        for fld in fields(spec.Palette):
            if fld.name in ("link", "visited"):
                continue
            cf = ColorField()
            cf.setToolTip(hints.get(fld.name, ""))
            cf.changed.connect(self.changed)
            self.colors[fld.name] = cf
            lbl = QLabel(fld.name.title())
            lbl.setToolTip(hints.get(fld.name, ""))
            f.addRow(lbl, cf)
        pick = QToolButton(text="Colors from an image", icon=QIcon.fromTheme("color-picker"),
                           toolButtonStyle=Qt.ToolButtonTextBesideIcon, popupMode=QToolButton.InstantPopup)
        pick.setToolTip("Make a readable palette from a picture: the background takes its main hue, the accent "
                        "its most colorful part")
        menu = QMenu(pick)
        self.img_wallpaper = menu.addAction(QIcon.fromTheme("preferences-desktop-wallpaper"),
                                            "From this theme's wallpaper", lambda: self.palette_from_image(None))
        menu.addAction(QIcon.fromTheme("document-open"), "From an image…", self.palette_from_image_file)
        menu.addSeparator()
        self.img_mode = QActionGroup(menu)
        for label, data in [("Dark or light: like the image", None), ("Dark theme", True), ("Light theme", False)]:
            a = menu.addAction(label)
            a.setCheckable(True)
            a.setData(data)
            a.setChecked(data is None)
            self.img_mode.addAction(a)
        menu.aboutToShow.connect(lambda: self.img_wallpaper.setEnabled(bool(self.theme.wallpaper)))
        pick.setMenu(menu)
        var = QPushButton(QIcon.fromTheme("color-management"), "Variations…")
        var.setToolTip("Nearby palettes (accent turned, warmer, cooler, more contrast…) as previews to pick from")
        var.clicked.connect(self.palette_variations)
        row = QHBoxLayout()
        row.addWidget(pick)
        row.addWidget(var)
        row.addStretch()
        v.addLayout(row)
        self.contrast = QLabel()
        self.contrast.setWordWrap(True)
        self.contrast.setTextFormat(Qt.RichText)
        v.addWidget(self.contrast)
        v.addStretch()
        return scroll(page)

    def _update_contrast(self) -> None:
        """Contrast ratio next to the text/accent fields, red when too low to read."""
        p = self.theme.palette.resolved()
        checks = [("Text on background", p.foreground, p.background, 4.5),
                  ("Text on surface", p.foreground, p.surface, 4.5),
                  ("Accent on background", p.accent, p.background, 3.0)]
        rows = []
        for label, a, b, need in checks:
            try:
                r = color.contrast(a, b)
            except ValueError:
                continue
            mark = "✓" if r >= need else "⚠ low"
            col = "" if r >= need else " style='color:#d4351c'"
            rows.append(f"<tr><td>{label}</td><td align=right{col}>&nbsp;&nbsp;{r:.1f}:1 {mark}</td></tr>")
        mode = "Dark" if self.theme.dark else "Light"
        self.contrast.setText(f"<b>{mode} theme</b> — readability (WCAG contrast)<table>{''.join(rows)}</table>")

    def palette_from_image_file(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Colors from an image", str(Path.home()),
                                           "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if f:
            self.palette_from_image(Path(f))

    def palette_from_image(self, path: Path | None) -> None:
        from ... import imagepalette
        path = path or Path(self.theme.wallpaper).expanduser()
        try:
            pal = imagepalette.from_image(path, self.img_mode.checkedAction().data(), self.theme.palette)
        except Exception as e:      # unreadable image
            QMessageBox.warning(self, "Colors from an image", str(e))
            return
        self._set_palette(pal, f"Colors taken from {path.name}. Ctrl+Z puts the old ones back.")

    def palette_variations(self) -> None:
        from ..variations_dialog import VariationsDialog
        dlg = VariationsDialog(self, copy.deepcopy(self.from_form()))
        if dlg.exec() == QDialog.Accepted and dlg.chosen:
            self._set_palette(dlg.chosen, "New colors. Ctrl+Z puts the old ones back.")

    def _set_palette(self, pal: spec.Palette, message: str) -> None:
        """Replace the palette as one undo step."""
        self._commit()
        self._loading = True
        for k, cf in self.colors.items():
            cf.set(getattr(pal, k))
        self._loading = False
        self.changed()
        self._commit()
        self.statusBar().showMessage(message, 8000)
