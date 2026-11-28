"""Before/after: the desktop you have now (a snapshot of the live config, drawn by the same Preview) left of a
draggable divider, the theme being edited right of it."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class CompareView(QWidget):
    resized = Signal()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.resized.emit()

    def __init__(self):
        super().__init__()
        self.before = QPixmap()
        self.after = QPixmap()
        self.before_label = "Your desktop now"
        self.after_label = ""
        self.split = 0.5                     # divider position, 0..1 of the width
        self.setMouseTracking(True)
        self.setCursor(Qt.SplitHCursor)
        self.setMinimumSize(320, 200)
        self.setToolTip("Drag to compare: your desktop now on the left, this theme on the right")

    def set_images(self, before: QPixmap, after: QPixmap, after_label: str) -> None:
        self.before, self.after, self.after_label = before, after, after_label
        self.update()

    def _move(self, x: float) -> None:
        self.split = min(1.0, max(0.0, x / max(1, self.width())))
        self.update()

    def mousePressEvent(self, e) -> None:
        self._move(e.position().x())

    def mouseMoveEvent(self, e) -> None:
        if e.buttons() & Qt.LeftButton:
            self._move(e.position().x())

    def keyPressEvent(self, e) -> None:
        step = {Qt.Key_Left: -0.05, Qt.Key_Right: 0.05}.get(e.key())
        if step is None:
            return super().keyPressEvent(e)
        self.split = min(1.0, max(0.0, self.split + step))
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x = round(self.width() * self.split)
        if not self.after.isNull():
            p.drawPixmap(0, 0, self.after)
        if not self.before.isNull():
            p.save()
            p.setClipRect(0, 0, x, self.height())
            p.drawPixmap(0, 0, self.before)
            p.restore()
        # divider + handle
        p.setPen(QPen(QColor(255, 255, 255, 230), 2))
        p.drawLine(x, 0, x, self.height())
        cy = self.height() / 2
        p.setBrush(QColor(255, 255, 255, 235))
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.drawEllipse(QPointF(x, cy), 15, 15)
        p.setPen(QPen(QColor(40, 40, 40), 2))
        for d in (-1, 1):
            arrow = QPainterPath(QPointF(x + d * 4, cy - 5))
            arrow.lineTo(x + d * 9, cy)
            arrow.lineTo(x + d * 4, cy + 5)
            p.drawPath(arrow)
        # labels
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        for text, left in ((self.before_label, True), (self.after_label, False)):
            if not text or (left and x < 60) or (not left and x > self.width() - 60):
                continue
            w = p.fontMetrics().horizontalAdvance(text) + 16
            r = QRectF(x - w - 10 if left else x + 10, 10, w, 24)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawRoundedRect(r, 6, 6)
            p.setPen(QColor("white"))
            p.drawText(r, Qt.AlignCenter, text)
