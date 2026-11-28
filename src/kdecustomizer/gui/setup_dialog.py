"""Setup check: `kdec doctor` as a window — what works here, and the install command for what doesn't.
The checks run on a worker thread (the image-AI one asks over the network); rows fill in as each one finishes."""
from __future__ import annotations

import html

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .. import doctor


class _Checker(QObject):
    """Runs doctor.run_iter() on a worker thread, one `found` signal per check."""

    found = Signal(object)          # a doctor.Check
    finished = Signal()

    def __init__(self, image_urls):
        super().__init__()
        self.image_urls = image_urls

    def run(self) -> None:
        try:
            for c in doctor.run_iter(self.image_urls):
                self.found.emit(c)
        finally:
            self.finished.emit()


class SetupDialog(QDialog):
    """kdec doctor as a window: what works here, install commands for the rest."""

    def __init__(self, parent=None, image_urls: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Setup Check")
        self.resize(720, 560)
        self.image_urls = [u for u in (image_urls or []) if u] or None
        self.checking: QThread | None = None
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
        self.again = QPushButton(QIcon.fromTheme("view-refresh"), "Check again")
        self.again.clicked.connect(self.refresh)
        box.addButton(self.again, QDialogButtonBox.ActionRole)
        box.rejected.connect(self.reject)
        v.addWidget(box)
        self.refresh()

    def refresh(self) -> None:
        """Rows for every check ('checking…'), then fill them in as results arrive."""
        if self.checking:
            return
        self.checks: list[doctor.Check] = []
        self.name, self.family = doctor.distro()
        grid_w = QWidget()
        self.grid = QGridLayout(grid_w)
        self.grid.setColumnStretch(1, 1)
        self.grid.setVerticalSpacing(10)
        self.rows: dict[str, tuple[QLabel, QLabel]] = {}
        for row, (key, label) in enumerate(doctor.ORDER):
            icon = QLabel()
            icon.setPixmap(QIcon.fromTheme("view-refresh").pixmap(22, 22))
            self.grid.addWidget(icon, row, 0, Qt.AlignTop)
            text = QLabel(f"<b>{html.escape(label)}</b> — <span style='color:palette(placeholder-text)'>"
                          "checking…</span>")
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.grid.addWidget(text, row, 1)
            self.rows[key] = (icon, text)
        self.grid.setRowStretch(len(doctor.ORDER), 1)
        self.area.setWidget(grid_w)
        self.copy.setEnabled(False)
        self.again.setEnabled(False)
        self._heading(done=False)
        self.checking = QThread(self)
        self.worker = _Checker(self.image_urls)
        self.worker.moveToThread(self.checking)
        self.checking.started.connect(self.worker.run)
        # bound methods so Qt runs them on the GUI thread
        self.worker.found.connect(self._found)
        self.worker.finished.connect(self._done)
        self.checking.start()

    def _heading(self, done: bool) -> None:
        """Distribution name and the summary line (checking / all work / n of m)."""
        missing = [c for c in self.checks if not c.ok]
        if not done:
            status = "Checking what works on this computer…"
        elif not missing:
            status = "Everything works here."
        else:
            status = (f"{len(self.checks) - len(missing)} of {len(self.checks)} work here. The others are only "
                      "needed for the features listed next to them.")
        self.heading.setText(f"<b>{html.escape(self.name)}</b>" + ("" if self.family else
                             " — commands below are generic: use your distribution's package manager")
                             + "<br>" + status)

    def _found(self, c: doctor.Check) -> None:
        self.checks.append(c)
        icon, text = self.rows.get(c.key) or self._extra_row(c.key)
        name_icon = "checkmark" if c.ok else ("dialog-error" if c.required else "dialog-information")
        icon.setPixmap(QIcon.fromTheme(name_icon, QIcon.fromTheme("dialog-ok" if c.ok else "dialog-warning"))
                       .pixmap(22, 22))
        fix = f"<br><code style='white-space:pre'>{html.escape(c.fix)}</code>" if c.fix else ""
        text.setText(f"<b>{html.escape(c.label)}</b> — {html.escape(c.purpose)}<br>"
                     f"<span style='color:palette(placeholder-text)'>{html.escape(c.detail)}</span>{fix}")

    def _extra_row(self, key: str) -> tuple[QLabel, QLabel]:
        row = self.grid.rowCount()
        icon, text = QLabel(), QLabel(wordWrap=True)
        self.grid.addWidget(icon, row, 0, Qt.AlignTop)
        self.grid.addWidget(text, row, 1)
        self.rows[key] = (icon, text)
        return icon, text

    def _done(self) -> None:
        self.checking.quit()
        self.checking.wait()
        self.checking = None
        self._heading(done=True)
        self.copy.setEnabled(bool(doctor.commands(self.checks)))
        self.again.setEnabled(True)

    def done(self, r: int) -> None:
        if self.checking:           # closing while checking: let the worker finish first
            self.checking.quit()
            self.checking.wait()
        super().done(r)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText("\n".join(doctor.commands(self.checks)))
        self.copy.setText("Copied")
