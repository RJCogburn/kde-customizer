"""Installed themes: what kde-customizer has put on this desktop, and removing what's no longer wanted."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QVBoxLayout,
)

from .. import installed


def _short(p: Path) -> str:
    home = str(Path.home())
    s = str(p)
    return "~" + s[len(home):] if s.startswith(home + "/") else s


class ThemeManager(QDialog):
    """Installed themes: their files, whether they're in use or changed since installing; Update and Remove."""

    update_requested = Signal(str)      # spec path: open it and apply it again

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Installed Themes")
        self.resize(720, 440)
        v = QVBoxLayout(self)
        intro = QLabel("Themes kde-customizer has installed for you. Removing one deletes its global theme, color "
                       "scheme, styles, icons, cursors, title bars and wallpaper copy. The theme you're using "
                       "can't be removed. Your theme files (.toml) are not touched.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._selected)
        row.addWidget(self.list, 2)
        right = QVBoxLayout()
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        self.info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right.addWidget(self.info, 1)
        self.remove_btn = QPushButton(QIcon.fromTheme("edit-delete"), "Remove")
        self.remove_btn.clicked.connect(self._remove)
        btns = QHBoxLayout()
        self.update_btn = QPushButton(QIcon.fromTheme("view-refresh"), "Update…")
        self.update_btn.setToolTip("Open its theme file and apply it again, so the desktop matches the file")
        self.update_btn.clicked.connect(self._update)
        btns.addWidget(self.update_btn)
        btns.addWidget(self.remove_btn)
        btns.addStretch()
        right.addLayout(btns)
        row.addLayout(right, 3)
        v.addLayout(row, 1)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        v.addWidget(box)
        self.refresh()

    def refresh(self) -> None:
        """Re-read installed themes and which ones changed since they were installed."""
        self.themes = installed.themes()
        self.outdated = installed.outdated()
        self.list.clear()
        for t in self.themes:
            busy = bool(t.in_use())
            text = t.name + (f"  (+ {', '.join(v.name for v in t.variants)})" if t.variants else "")
            notes = (["in use"] if busy else []) + (["changed since installed"] if t.id in self.outdated else [])
            icon = ("update-none" if t.id in self.outdated else "checkmark" if busy
                    else "preferences-desktop-theme-global")
            it = QListWidgetItem(QIcon.fromTheme(icon, QIcon.fromTheme("preferences-desktop-theme-global")),
                                 text + (f"  — {', '.join(notes)}" if notes else ""))
            it.setData(Qt.UserRole, t.id)
            self.list.addItem(it)
        if self.themes:
            self.list.setCurrentRow(0)
        else:
            self.info.setText("No kde-customizer themes are installed.")
            self.remove_btn.setEnabled(False)
            self.update_btn.setEnabled(False)

    def _theme(self) -> installed.Installed | None:
        it = self.list.currentItem()
        return next((t for t in self.themes if it and t.id == it.data(Qt.UserRole)), None)

    def _selected(self, *_) -> None:
        """Details of the selected theme: why it can't be removed, whether to update it, its files."""
        t = self._theme()
        if not t:
            return
        why = t.in_use()
        parts = "".join(f"<li>{_short(p)}</li>" for p in t.parts())
        status = (f"<p style='color:palette(link-visited)'>In use: {', '.join(why)}. Switch to another theme "
                  "first (System Settings › Colors &amp; Themes, or Apply another one).</p>" if why else "")
        spec = self.outdated.get(t.id)
        if spec:
            status += (f"<p><b>Your theme file has changed since this was installed</b> ({_short(spec)}). "
                       "Update applies it again.</p>")
        self.info.setText(f"<b>{t.name}</b><br><small>{t.id}</small>{status}<p>Files:</p><ul>{parts}</ul>")
        self.update_btn.setVisible(bool(spec))
        self.remove_btn.setEnabled(not why)
        self.remove_btn.setToolTip("" if not why else "In use: " + ", ".join(why))

    def _update(self) -> None:
        t = self._theme()
        if t and (spec := self.outdated.get(t.id)):
            self.update_requested.emit(str(spec))
            self.accept()

    def _remove(self) -> None:
        """Remove the selected theme and all its parts (after asking)."""
        t = self._theme()
        if not t:
            return
        n = len(t.parts())
        r = QMessageBox.question(self, "Remove theme",
                                 f"Remove “{t.name}” and its {n} installed part(s)?\n\nThis can't be undone, but you "
                                 "can install it again by applying its theme file.")
        if r != QMessageBox.Yes:
            return
        try:
            installed.remove(t)
        except (RuntimeError, OSError) as e:
            QMessageBox.warning(self, "Remove theme", str(e))
        self.refresh()
