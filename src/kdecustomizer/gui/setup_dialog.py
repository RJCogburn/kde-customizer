"""Setup check: `kdec doctor` as a window — what works here, and the install command for what doesn't."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QGridLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .. import doctor


class SetupDialog(QDialog):
    def __init__(self, parent=None, image_urls: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Setup Check")
        self.resize(720, 560)
        self.image_urls = [u for u in (image_urls or []) if u] or None
        v = QVBoxLayout(self)
        self.heading = QLabel()
        self.heading.setWordWrap(True)
        v.addWidget(self.heading)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        v.addWidget(self.area, 1)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        self.copy = QPushButton(QIcon.fromTheme("edit-copy"), "Copy install commands")
        self.copy.setToolTip("Copy the commands for everything missing, to paste into a terminal")
        self.copy.clicked.connect(self._copy)
        box.addButton(self.copy, QDialogButtonBox.ActionRole)
        again = QPushButton(QIcon.fromTheme("view-refresh"), "Check again")
        again.clicked.connect(self.refresh)
        box.addButton(again, QDialogButtonBox.ActionRole)
        box.rejected.connect(self.reject)
        v.addWidget(box)
        self.refresh()

    def refresh(self) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.checks = doctor.run(self.image_urls)
        finally:
            QApplication.restoreOverrideCursor()
        name, family = doctor.distro()
        missing = [c for c in self.checks if not c.ok]
        self.heading.setText(
            f"<b>{html.escape(name)}</b>" + ("" if family else " — commands below are generic: use your "
                                              "distribution's package manager") + "<br>"
            + ("Everything works here." if not missing else
               f"{len(self.checks) - len(missing)} of {len(self.checks)} work here. The others are only needed "
               "for the features listed next to them."))
        grid_w = QWidget()
        g = QGridLayout(grid_w)
        g.setColumnStretch(1, 1)
        g.setVerticalSpacing(10)
        for row, c in enumerate(self.checks):
            icon = QLabel()
            name_icon = "checkmark" if c.ok else ("dialog-error" if c.required else "dialog-information")
            icon.setPixmap(QIcon.fromTheme(name_icon, QIcon.fromTheme("dialog-ok" if c.ok else "dialog-warning"))
                           .pixmap(22, 22))
            g.addWidget(icon, row, 0, Qt.AlignTop)
            fix = (f"<br><code style='white-space:pre'>{html.escape(c.fix)}</code>" if c.fix else "")
            text = QLabel(f"<b>{html.escape(c.label)}</b> — {html.escape(c.purpose)}<br>"
                          f"<span style='color:palette(placeholder-text)'>{html.escape(c.detail)}</span>{fix}")
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            g.addWidget(text, row, 1)
        g.setRowStretch(len(self.checks), 1)
        self.area.setWidget(grid_w)
        self.copy.setEnabled(bool(doctor.commands(self.checks)))

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText("\n".join(doctor.commands(self.checks)))
        self.copy.setText("Copied")
