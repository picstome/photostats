"""Small vector icons, drawn rather than taken from a font.

The gear and sun used to be Unicode characters, and they rendered as emoji or
as tofu boxes depending on the platform's font fallback — which is why the
settings and theme buttons looked broken. Drawing them means they look the same
everywhere and can use the theme's own colours.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

#: Sizes baked into every icon. Qt picks the closest one instead of scaling,
#: and scaling a 20px drawing down to 18px is what made these look fuzzy.
ICON_SIZES = (16, 18, 20, 24, 32)


def _pixmap(size: int, colour: str, draw) -> QIcon:
    """Render *draw* at each of :data:`ICON_SIZES` and return them as one icon."""
    icon = QIcon()
    for edge in ICON_SIZES:
        pixmap = QPixmap(edge, edge)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor(colour))
        painter.setBrush(QColor(colour))
        draw(painter, edge)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def gear(colour: str, size: int = 20) -> QIcon:
    """A cog: a ring with eight teeth."""

    def draw(painter: QPainter, side: int) -> None:
        centre = side / 2
        # A pen built from the colour, not from painter.pen(): that one still
        # carries Qt.NoPen's style, and setting a width on it changes nothing,
        # so the whole icon silently failed to draw.
        # A gear is a *thick* ring with teeth that touch it. Drawn as a thin ring
        # with detached rays it was indistinguishable from the sun beside it,
        # which is no use to anyone.
        pen = QPen(QColor(colour), max(2.0, side * 0.15))
        pen.setCapStyle(Qt.SquareCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(centre, centre), side * 0.20, side * 0.20)
        for angle in range(0, 360, 60):
            painter.save()
            painter.translate(centre, centre)
            painter.rotate(angle)
            painter.drawLine(QPointF(side * 0.28, 0), QPointF(side * 0.44, 0))
            painter.restore()

    return _pixmap(size, colour, draw)


def sun(colour: str, size: int = 20) -> QIcon:
    """A sun: a disc with eight rays."""

    def draw(painter: QPainter, side: int) -> None:
        centre = side / 2
        # A *filled* disc with detached rays, so it stays clearly not a gear.
        pen = QPen(QColor(colour), max(1.4, side * 0.075))
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(QColor(colour))
        painter.drawEllipse(QPointF(centre, centre), side * 0.17, side * 0.17)
        painter.setBrush(Qt.NoBrush)
        for angle in range(0, 360, 45):
            painter.save()
            painter.translate(centre, centre)
            painter.rotate(angle)
            painter.drawLine(QPointF(side * 0.30, 0), QPointF(side * 0.46, 0))
            painter.restore()

    return _pixmap(size, colour, draw)


def moon(colour: str, size: int = 20) -> QIcon:
    """A crescent, for the dark side of the theme toggle."""

    def draw(painter: QPainter, side: int) -> None:
        centre = side / 2
        path = QPainterPath()
        path.addEllipse(QPointF(centre, centre), side * 0.30, side * 0.30)
        painter.setPen(Qt.NoPen)
        painter.drawPath(path)
        # Cut the lit part away, leaving a crescent. The clear composition mode
        # needs a real brush, so this is drawn as a filled ellipse.
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.setBrush(QColor(colour))
        painter.drawEllipse(QPointF(centre + side * 0.13, centre - side * 0.05),
                            side * 0.26, side * 0.26)

    return _pixmap(size, colour, draw)


def chevron_down(colour: str, size: int = 12) -> QIcon:
    """The small arrow that says "this button has a menu"."""

    def draw(painter: QPainter, side: int) -> None:
        pen = QPen(QColor(colour), max(1.2, side * 0.14))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        path = QPainterPath(QPointF(side * 0.18, side * 0.32))
        path.lineTo(QPointF(side * 0.5, side * 0.68))
        path.lineTo(QPointF(side * 0.82, side * 0.32))
        painter.drawPath(path)

    return _pixmap(size, colour, draw)
