from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def icon(name: str, color: str = "#aeb6cf", size: int = 20) -> QIcon:
    """Return a small, consistent line icon without an external icon dependency."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    inset, span = 3.0, float(size - 6)

    if name in {"mic", "capture"}:
        painter.drawRoundedRect(QRectF(size * .38, inset, size * .24, size * .50), size * .12, size * .12)
        path = QPainterPath(QPointF(size * .27, size * .49))
        path.cubicTo(size * .27, size * .75, size * .73, size * .75, size * .73, size * .49)
        painter.drawPath(path)
        painter.drawLine(QPointF(size * .50, size * .74), QPointF(size * .50, size * .88))
        painter.drawLine(QPointF(size * .37, size * .88), QPointF(size * .63, size * .88))

    elif name == "image":
        painter.drawRoundedRect(QRectF(inset, inset + 1, span, span - 2), 2, 2)
        painter.drawEllipse(QRectF(size * .60, size * .34, 2.5, 2.5))
        path = QPainterPath(QPointF(size * .20, size * .72))
        path.lineTo(QPointF(size * .40, size * .52))
        path.lineTo(QPointF(size * .53, size * .64))
        path.lineTo(QPointF(size * .66, size * .48))
        path.lineTo(QPointF(size * .82, size * .72))
        painter.drawPath(path)

    elif name == "history":
        painter.drawEllipse(QRectF(inset, inset, span, span))
        painter.drawLine(QPointF(size * .50, size * .50), QPointF(size * .50, size * .31))
        painter.drawLine(QPointF(size * .50, size * .50), QPointF(size * .65, size * .60))

    elif name == "settings":
        painter.drawEllipse(QRectF(size * .38, size * .38, size * .24, size * .24))
        for x1, y1, x2, y2 in ((.50, .12, .50, .28), (.50, .72, .50, .88), (.12, .50, .28, .50), (.72, .50, .88, .50),
                                (.23, .23, .34, .34), (.66, .66, .77, .77), (.77, .23, .66, .34), (.34, .66, .23, .77)):
            painter.drawLine(QPointF(size * x1, size * y1), QPointF(size * x2, size * y2))

    elif name == "copy":
        painter.drawRoundedRect(QRectF(size * .34, size * .20, size * .48, size * .58), 2, 2)
        painter.drawRoundedRect(QRectF(size * .18, size * .36, size * .48, size * .50), 2, 2)

    elif name == "stop":
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(size * .29, size * .29, size * .42, size * .42), 2, 2)

    elif name == "shield":
        path = QPainterPath(QPointF(size * .50, size * .12))
        path.lineTo(QPointF(size * .78, size * .23))
        path.lineTo(QPointF(size * .73, size * .62))
        path.quadTo(QPointF(size * .62, size * .80), QPointF(size * .50, size * .88))
        path.quadTo(QPointF(size * .38, size * .80), QPointF(size * .27, size * .62))
        path.lineTo(QPointF(size * .22, size * .23))
        path.closeSubpath()
        painter.drawPath(path)

    elif name == "font":
        # Stylised "A" letter — Create Font
        path = QPainterPath(QPointF(size * .50, size * .14))
        path.lineTo(QPointF(size * .22, size * .86))
        painter.drawPath(path)
        path2 = QPainterPath(QPointF(size * .50, size * .14))
        path2.lineTo(QPointF(size * .78, size * .86))
        painter.drawPath(path2)
        painter.drawLine(QPointF(size * .31, size * .60), QPointF(size * .69, size * .60))

    elif name == "files":
        # Stacked pages / files icon
        # Back page
        painter.drawRoundedRect(QRectF(size * .26, size * .20, size * .52, size * .62), 2.0, 2.0)
        # Folded corner
        painter.drawLine(QPointF(size * .62, size * .20), QPointF(size * .78, size * .36))
        painter.drawLine(QPointF(size * .62, size * .20), QPointF(size * .62, size * .36))
        painter.drawLine(QPointF(size * .62, size * .36), QPointF(size * .78, size * .36))
        # Lines on page
        pen2 = QPen(QColor(color), 1.2)
        pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen2)
        painter.drawLine(QPointF(size * .36, size * .51), QPointF(size * .64, size * .51))
        painter.drawLine(QPointF(size * .36, size * .61), QPointF(size * .64, size * .61))
        painter.drawLine(QPointF(size * .36, size * .71), QPointF(size * .54, size * .71))

    elif name == "chevron_left":
        path = QPainterPath(QPointF(size * .62, size * .22))
        path.lineTo(QPointF(size * .34, size * .50))
        path.lineTo(QPointF(size * .62, size * .78))
        painter.drawPath(path)

    elif name == "chevron_right":
        path = QPainterPath(QPointF(size * .38, size * .22))
        path.lineTo(QPointF(size * .66, size * .50))
        path.lineTo(QPointF(size * .38, size * .78))
        painter.drawPath(path)

    elif name == "check":
        path = QPainterPath(QPointF(size * .20, size * .50))
        path.lineTo(QPointF(size * .42, size * .72))
        path.lineTo(QPointF(size * .80, size * .28))
        painter.drawPath(path)

    elif name == "download":
        # Arrow pointing down, then a line at bottom
        painter.drawLine(QPointF(size * .50, size * .16), QPointF(size * .50, size * .72))
        path = QPainterPath(QPointF(size * .30, size * .54))
        path.lineTo(QPointF(size * .50, size * .74))
        path.lineTo(QPointF(size * .70, size * .54))
        painter.drawPath(path)
        painter.drawLine(QPointF(size * .20, size * .84), QPointF(size * .80, size * .84))

    elif name == "upload":
        painter.drawLine(QPointF(size * .50, size * .74), QPointF(size * .50, size * .18))
        path = QPainterPath(QPointF(size * .30, size * .36))
        path.lineTo(QPointF(size * .50, size * .16))
        path.lineTo(QPointF(size * .70, size * .36))
        painter.drawPath(path)
        painter.drawLine(QPointF(size * .20, size * .84), QPointF(size * .80, size * .84))

    elif name == "translate":
        # Two stacked curved arrows suggesting bidirectional translation
        # Top arrow: left to right
        path = QPainterPath(QPointF(size * .18, size * .36))
        path.cubicTo(size * .18, size * .22, size * .82, size * .22, size * .82, size * .36)
        painter.drawPath(path)
        # Arrowhead right
        arr1 = QPainterPath(QPointF(size * .68, size * .26))
        arr1.lineTo(QPointF(size * .82, size * .36))
        arr1.lineTo(QPointF(size * .70, size * .47))
        painter.drawPath(arr1)
        # Bottom arrow: right to left
        path2 = QPainterPath(QPointF(size * .82, size * .64))
        path2.cubicTo(size * .82, size * .78, size * .18, size * .78, size * .18, size * .64)
        painter.drawPath(path2)
        # Arrowhead left
        arr2 = QPainterPath(QPointF(size * .32, size * .74))
        arr2.lineTo(QPointF(size * .18, size * .64))
        arr2.lineTo(QPointF(size * .30, size * .53))
        painter.drawPath(arr2)

    painter.end()
    return QIcon(pixmap)
