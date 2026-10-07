"""A card showing one attribute as a horizontal bar chart.

Painted by hand rather than with QtCharts so that the look is identical on every
platform, the drawing is cheap enough for hundreds of bars, and clicks can be
mapped back to filter values without an overlay.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...core.queries import FacetResult

#: Fixed label and count widths looked fine while cards were three abreast and
#: quietly destroyed the chart once they were four: 124 + 64 out of a 228px card
#: left 28px of actual data. Both are now derived from the content.
#: The label is measured, because "f/1.8" needs a fraction of what "NIKKOR Z
#: 24-70mm f/2.8 S" does, and reserving the same room for both wastes the card.
LABEL_MIN = 44
LABEL_MAX = 130
#: The bar must be able to show a difference at all.
TRACK_MIN = 60
COUNT_MIN = 46
COUNT_MAX = 104
ROW_HEIGHT = 21
BAR_HEIGHT = 10
PADDING = 6
GAP = 3


class BarChart(QWidget):
    """Horizontal bars; clicking a bar toggles that value as a filter."""

    bar_clicked = Signal(str)      # facet key of the value
    bar_hovered = Signal(str, str)  # (label, tooltip)

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self._colors: dict[str, QColor] = {}
        self.facet = ""
        self.result: FacetResult | None = None
        self.selected: set[str] = set()
        self._rows: list[tuple[str, str, int, QRectF]] = []
        self._hover = -1
        self._pressed = -1
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

    # -- data --------------------------------------------------------------
    def _label_width(self) -> int:
        """How much room the value names need, given how much room there is.

        Measured from the labels actually in this chart, then capped by what
        the card can spare: a chart of f-stops hands most of its width to the
        bar, one of lens names keeps what it needs and no more.
        """
        count_w = self._count_width()
        room = self.width() - count_w - PADDING * 2 - 10
        ceiling = room - TRACK_MIN
        if ceiling <= LABEL_MIN:
            return max(LABEL_MIN, room - TRACK_MIN)
        metrics = self.fontMetrics()
        wanted = max(
            (metrics.horizontalAdvance(str(b.label)) + 10
             for b in self.buckets()), default=LABEL_MIN)
        return min(LABEL_MAX, max(LABEL_MIN, min(int(wanted), ceiling)))

    def _color(self, name: str) -> QColor:
        """QColor construction is not free; a chart repaints on every hover."""
        colour = self._colors.get(name)
        if colour is None:
            colour = QColor(name)
            self._colors[name] = colour
        return colour

    def set_result(self, result: FacetResult, selected: set[str] | None = None) -> None:
        self.facet = result.facet
        self.result = result
        self.selected = set(selected or ())
        self._layout_rows()
        self.update()

    def set_selected(self, selected: set[str]) -> None:
        self.selected = set(selected)
        self.update()

    def clear(self) -> None:
        self.facet = ""
        self.result = None
        self.selected = set()
        self._rows.clear()
        self._layout_rows()
        self.update()

    # -- geometry ----------------------------------------------------------
    #: Bars actually drawn. The owning card sizes itself from this number, so
    #: painting must never exceed it.
    max_bars = 8

    def buckets(self, limit: int | None = None) -> list:
        if self.result is None:
            return []
        return self.result.buckets[: limit or self.max_bars]

    def _right_text(self, bucket) -> str:
        """Count and share together: '1,055 · 94%'.

        The count alone did not say whether a bucket dominated; the share is
        what makes a facet readable at a glance, and it is what the tooltip
        has been reporting all along.
        """
        return f"{bucket.count:,} · {bucket.share * 100:.0f}%"

    def _count_width(self) -> int:
        """How much room the 'count · share' column needs, measured."""
        metrics = self.fontMetrics()
        wanted = max(
            (metrics.horizontalAdvance(self._right_text(b)) for b in self.buckets()),
            default=0,
        )
        if not wanted:
            return COUNT_MIN
        return min(COUNT_MAX, max(COUNT_MIN, int(wanted)))

    def _layout_rows(self) -> None:
        self._rows.clear()
        height = PADDING * 2 + len(self.buckets()) * ROW_HEIGHT
        self.setFixedHeight(height)
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        rows = len(self.buckets())
        return QSize(320, PADDING * 2 + rows * ROW_HEIGHT)

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: D102, N802 - Qt naming
        if self.result is None or not self.result.buckets:
            return
        painter = QPainter(self)
        try:
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        font = painter.font()
        metrics = QFontMetrics(font)

        buckets = self.buckets()
        peak = max((b.share for b in buckets), default=1.0) or 1.0
        count_w = self._count_width()
        air = 10
        for index, bucket in enumerate(buckets):
            top = PADDING + index * ROW_HEIGHT
            row_rect = QRectF(0, top, self.width(), ROW_HEIGHT)
            if index == self._hover:
                painter.setPen(Qt.NoPen)
                painter.setBrush(self._color(self.theme.card_hover))
                painter.drawRoundedRect(row_rect.adjusted(2, 1, -2, -1), 6, 6)

            is_selected = str(bucket.label) in self.selected
            text_color = QColor(self.theme.text if is_selected else self.theme.text_dim)
            label_w = self._label_width()
            label_rect = QRectF(PADDING, top, label_w - 8, ROW_HEIGHT)
            label = metrics.elidedText(str(bucket.label), Qt.ElideRight, int(label_w - 10))
            painter.setPen(text_color)
            painter.drawText(label_rect, Qt.AlignVCenter | Qt.AlignLeft, label)

            count_w = self._count_width()
            # Ten pixels of air between a full bar and its figures; six felt
            # like the count was leaning on the bar's end.
            air = 10
            track = QRectF(PADDING + label_w, top + (ROW_HEIGHT - BAR_HEIGHT) / 2,
                           max(TRACK_MIN, self.width() - label_w - count_w - PADDING * 2 - air),
                           BAR_HEIGHT)
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._color(self.theme.bar_bg))
            painter.drawRoundedRect(track, BAR_HEIGHT / 2, BAR_HEIGHT / 2)

            value = bucket.share / peak
            bar = QRectF(track.x(), track.y(), max(BAR_HEIGHT, track.width() * value), BAR_HEIGHT)
            painter.setBrush(QColor(self.theme.accent if is_selected else self.theme.accent_dim))
            painter.drawRoundedRect(bar, BAR_HEIGHT / 2, BAR_HEIGHT / 2)

            count_rect = QRectF(self.width() - count_w - PADDING, top, count_w, ROW_HEIGHT)
            painter.setPen(
                QColor(self.theme.text if is_selected else self.theme.text_faint)
            )
            painter.drawText(count_rect, Qt.AlignVCenter | Qt.AlignRight,
                             self._right_text(bucket))

    # -- interaction -------------------------------------------------------
    def mouseMoveEvent(self, event) -> None:  # noqa: D102, N802
        index = self._index_at(event.position().y())
        if index != self._hover:
            self._hover = index
            self.setCursor(Qt.PointingHandCursor if index >= 0 else Qt.ArrowCursor)
            if self.result is not None and 0 <= index < len(self.buckets()):
                bucket = self.buckets()[index]
                tooltip = f"{bucket.label} — {bucket.count:,} photos ({bucket.share * 100:.1f}%)"
                self.bar_hovered.emit(str(bucket.label), tooltip)
                self.setToolTip(tooltip)
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: D102, N802
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: D102, N802
        self._pressed = self._index_at(event.position().y())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: D102, N802
        index = self._index_at(event.position().y())
        if index >= 0 and index == self._pressed and self.result is not None:
            bucket = self.buckets()[index]
            self.bar_clicked.emit(str(bucket.label))
        self._pressed = -1
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: D102, N802
        """Left/Right arrows move between bars, Space or Enter toggles one."""
        if not self.result or not self.buckets():
            return
        count = len(self.buckets())
        if event.key() in (Qt.Key_Left, Qt.Key_Up):
            self._hover = (self._hover - 1) % count if self._hover >= 0 else count - 1
            self.update()
        elif event.key() in (Qt.Key_Right, Qt.Key_Down):
            self._hover = (self._hover + 1) % count
            self.update()
        elif event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            if 0 <= self._hover < count:
                self.bar_clicked.emit(str(self.buckets()[self._hover].label))
        else:
            super().keyPressEvent(event)

    def _index_at(self, y: float) -> int:
        if not self.result or not self.result.buckets:
            return -1
        if y < PADDING or y > PADDING + len(self.buckets()) * ROW_HEIGHT:
            return -1
        return int((y - PADDING) // ROW_HEIGHT)


class DonutChart(QWidget):
    """Small ring used for the filtered/total proportion."""

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self._value = 0.0
        self._label = ""
        self.setFixedSize(52, 52)

    def set_value(self, fraction: float, label: str = "") -> None:
        self._value = max(0.0, min(1.0, fraction))
        self._label = label
        self.update()

    def paintEvent(self, event) -> None:  # noqa: D102, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        size = min(self.width(), self.height()) - 6
        rect = QRectF((self.width() - size) / 2, (self.height() - size) / 2, size, size)
        pen = QPen(self._color(self.theme.bar_bg), 5)
        painter.setPen(pen)
        painter.drawArc(rect.adjusted(3, 3, -3, -3), 0, 360 * 16)
        if self._value > 0:
            painter.setPen(QPen(self._color(self.theme.accent), 5, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(rect.adjusted(3, 3, -3, -3), 90 * 16, -int(360 * 16 * self._value))
        painter.setPen(self._color(self.theme.text))
        font = painter.font()
        font.setPointSizeF(max(7.0, font.pointSizeF() * 0.8))
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self._label or f"{self._value * 100:.0f}%")
        painter.end()
