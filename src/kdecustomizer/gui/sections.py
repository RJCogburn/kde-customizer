"""The editor's sections as a sidebar (icon above name) beside the page, like System Settings — every section stays
in view at any width, where a tab bar ran out of room. Same API as the QTabWidget it replaces."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QListView, QListWidget, QListWidgetItem, QStackedWidget, QWidget

WIDTH = 84


class Sections(QWidget):
    """Icon sidebar + stacked pages with QTabWidget's API (addTab, tabText, setCurrentIndex, currentChanged)."""

    currentChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self.list = QListWidget()
        self.list.setViewMode(QListView.IconMode)
        self.list.setFlow(QListView.TopToBottom)
        self.list.setMovement(QListView.Static)
        self.list.setWrapping(False)
        self.list.setIconSize(QSize(28, 28))
        self.list.setSpacing(2)
        self.list.setFixedWidth(WIDTH)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setStyleSheet("QListWidget { background: palette(alternate-base); }")
        self.list.setAccessibleName("Sections")
        self.stack = QStackedWidget()
        self.list.currentRowChanged.connect(self._row)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.list)
        sep = QFrame(frameShape=QFrame.VLine, frameShadow=QFrame.Sunken)
        lay.addWidget(sep)
        lay.addWidget(self.stack, 1)

    def addTab(self, widget: QWidget, text: str, icon: str = "") -> int:
        """Add a page with a sidebar entry; returns its index."""
        it = QListWidgetItem(QIcon.fromTheme(icon), text)
        it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
        it.setSizeHint(QSize(WIDTH - 8, 58))
        it.setToolTip(text)
        self.list.addItem(it)
        i = self.stack.addWidget(widget)
        if self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        return i

    def _row(self, row: int) -> None:
        if row >= 0:
            self.stack.setCurrentIndex(row)
            self.currentChanged.emit(row)

    def count(self) -> int:
        return self.stack.count()

    def currentIndex(self) -> int:
        return self.stack.currentIndex()

    def setCurrentIndex(self, i: int) -> None:
        self.list.setCurrentRow(i)

    def tabText(self, i: int) -> str:
        it = self.list.item(i)
        return it.text() if it else ""

    def widget(self, i: int) -> QWidget:
        return self.stack.widget(i)

    def currentWidget(self) -> QWidget:
        return self.stack.currentWidget()
