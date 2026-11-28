"""Find a setting: a search box over every section's labels, checkboxes, buttons and group titles (and their
tooltips). Picking a match switches to its section, scrolls to the control, focuses it and outlines it briefly."""
from __future__ import annotations

import re

from PySide6.QtCore import QModelIndex, Qt, QTimer
from PySide6.QtGui import QIcon, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractButton, QCompleter, QFormLayout, QGroupBox, QLabel, QLayout, QLineEdit, QRubberBand, QScrollArea,
    QWidget,
)

def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "").replace("&&", "\0").replace("&", "").replace("\0", "&")
    return " ".join(text.split()).rstrip(":").strip()


def _form_field(label: QLabel) -> QWidget | None:
    """The control a form label belongs to."""
    if label.buddy():
        return label.buddy()
    parent = label.parentWidget()
    if parent is None:
        return None
    for form in parent.findChildren(QFormLayout):
        row, role = form.getWidgetPosition(label)
        if row >= 0 and role == QFormLayout.LabelRole:
            item = form.itemAt(row, QFormLayout.FieldRole)
            if item is None:
                return None
            if item.widget():
                return item.widget()
            lay: QLayout | None = item.layout()
            for i in range(lay.count() if lay else 0):
                if w := lay.itemAt(i).widget():
                    return w
    return None


def entries(sections) -> list[tuple[str, int, QWidget, str]]:
    """[(text, section index, widget to show, tooltip)] for every labelled control in the sections."""
    out: list[tuple[str, int, QWidget, str]] = []
    seen: set[tuple[str, int]] = set()
    for i in range(sections.count()):
        page = sections.widget(i)
        out.append((sections.tabText(i), i, page, ""))
        for w in page.findChildren(QWidget):
            target = w
            if isinstance(w, QGroupBox):
                text = w.title()
            elif isinstance(w, QAbstractButton):
                text = w.text()
            elif isinstance(w, QLabel):
                text = w.text()
                if len(_clean(text)) > 50:          # explanations, not names of settings
                    continue
                target = _form_field(w) or w
            else:
                continue
            text = _clean(text)
            if len(text) < 3 or (text, i) in seen:
                continue
            seen.add((text, i))
            out.append((text, i, target, _clean(w.toolTip() or target.toolTip())))
    return out


class SettingFinder(QLineEdit):
    """`go(section index, widget)` is called when a match is picked. Matches in a control's own text come first,
    then those found only in its tooltip."""

    def __init__(self, sections, go):
        super().__init__()
        self.sections, self.go = sections, go
        self.setPlaceholderText("Find a setting…  (Ctrl+F)")
        self.setClearButtonEnabled(True)
        self.addAction(QIcon.fromTheme("search"), QLineEdit.LeadingPosition)
        self.index: list[tuple[str, int, QWidget, str]] = []
        self.model = QStandardItemModel(self)
        self.completer_ = QCompleter(self.model, self)
        self.completer_.setCompletionMode(QCompleter.UnfilteredPopupCompletion)     # we filter and rank
        self.completer_.setMaxVisibleItems(12)
        self.completer_.setWidget(self)
        self.completer_.activated[QModelIndex].connect(self._picked)
        self.textEdited.connect(self._search)
        self.returnPressed.connect(self._first)

    def reindex(self) -> None:
        self.index = entries(self.sections)

    def matches(self, query: str) -> list[int]:
        """Indexes into self.index, best first."""
        q = query.lower().strip()
        if not q:
            return []
        ranked = []
        for n, (text, i, _w, tip) in enumerate(self.index):
            t = text.lower()
            if t.startswith(q):
                rank = 0
            elif q in t:
                rank = 1
            elif q in tip.lower() or q in self.sections.tabText(i).lower():
                rank = 2
            else:
                continue
            ranked.append((rank, n))
        return [n for _r, n in sorted(ranked)]

    def _search(self, text: str) -> None:
        """Fill the popup with the best matches for the typed text."""
        if not self.index:
            self.reindex()
        self.model.clear()
        for n in self.matches(text)[:40]:
            label, i, w, tip = self.index[n]
            it = QStandardItem(f"{label}   ·   {self.sections.tabText(i)}" if w is not self.sections.widget(i)
                               else f"{label}   (section)")
            it.setData(n, Qt.UserRole)
            it.setToolTip(tip)
            self.model.appendRow(it)
        if self.model.rowCount():
            self.completer_.complete()
        else:
            self.completer_.popup().hide()

    def _first(self) -> None:
        idx = self.model.index(0, 0)
        if idx.isValid():
            self._picked(idx)

    def _picked(self, index: QModelIndex) -> None:
        n = index.data(Qt.UserRole)
        if n is None:
            return
        self.completer_.popup().hide()
        QTimer.singleShot(0, self.clear)
        _label, section, widget, _tip = self.index[n]
        self.go(section, widget)


def reveal(widget: QWidget) -> None:
    """Scroll to a control, focus it and outline it for a moment."""
    parent = widget.parentWidget()
    while parent is not None and not isinstance(parent, QScrollArea):
        parent = parent.parentWidget()
    if isinstance(parent, QScrollArea):
        parent.ensureWidgetVisible(widget, 40, 60)
    if widget.focusPolicy() != Qt.NoFocus:
        widget.setFocus(Qt.ShortcutFocusReason)
    if widget.parentWidget() is None:
        return
    band = QRubberBand(QRubberBand.Rectangle, widget.parentWidget())
    band.setGeometry(widget.geometry().adjusted(-4, -3, 4, 3))
    band.show()
    QTimer.singleShot(1600, band.deleteLater)
