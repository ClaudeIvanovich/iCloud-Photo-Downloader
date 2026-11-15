"""Generated application and tray icons. No third-party artwork or logos."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

STATE_COLORS = {
    "idle": "#4A6FA5",  # waiting
    "active": "#2E9E5B",  # downloading
    "error": "#C8443C",
}


def render(state: str = "idle", size: int = 64) -> QPixmap:
    """A rounded square with a 'download into a tray' arrow, coloured by state."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    unit = size / 64.0
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(STATE_COLORS.get(state, STATE_COLORS["idle"])))
    painter.drawRoundedRect(QRectF(2 * unit, 2 * unit, 60 * unit, 60 * unit), 14 * unit, 14 * unit)

    white = QColor("#FFFFFF")
    pen = QPen(white, 6 * unit, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(QPointF(32 * unit, 14 * unit), QPointF(32 * unit, 34 * unit))  # shaft
    painter.setBrush(white)
    painter.setPen(QPen(white, 2 * unit, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawPolygon(
        QPolygonF([QPointF(20 * unit, 30 * unit), QPointF(44 * unit, 30 * unit), QPointF(32 * unit, 43 * unit)])
    )
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(QPointF(17 * unit, 50 * unit), QPointF(47 * unit, 50 * unit))  # tray
    painter.end()
    return pixmap


def icon(state: str = "idle") -> QIcon:
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        result.addPixmap(render(state, size))
    return result
