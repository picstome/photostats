"""Photos-per-period chart with a draggable date-range selection.

Dragging across the bars sets the date filter; double-clicking clears it.
"""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...core.queries import Timeline

HEIGHT = 104
LABEL_HEIGHT = 20
PADDING = 10
BAR_MIN_WIDTH = 3
#: Smallest a bar is drawn, so a month is never literally invisible.
MIN_BAR = 3.0
GAP = 3


class TimelineChart(QWidget):
    """Bar chart over time; drag selects a range of periods."""

    range_selected = Signal(object, object)  # (date | None, date | None)
    cleared = Signal()

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.timeline: Timeline | None = None
        self.selection: tuple[date | None, date | None] = (None, None)
        self._dragging = False
        self._anchor = 0
        self._bars: list[tuple[date, QRectF]] = []
        #: Index of the bar under the pointer, for the hover highlight.
        self._hover: int | None = None
        self.setFixedHeight(HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Without mouse tracking no move events arrive while the button is up,
        # so there would be no tooltip and no hover highlight.
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def set_timeline(self, timeline: Timeline, selection: tuple[date | None, date | None]) -> None:
        self.timeline = timeline
        self.selection = selection
        self._layout()
        self.update()

    def clear(self) -> None:
        self.timeline = None
        self.selection = (None, None)
        self._bars.clear()
        self._hover = None
        self.setToolTip("")
        self.update()

    def tooltip_for(self, x: float) -> str:
        index = self._index_at(x)
        if not self._bars or not 0 <= index < len(self._bars):
            return ""
        day, rect = self._bars[index]
        count = self.timeline.points[index][1]
        granularity = self.timeline.granularity if self.timeline else "day"
        _first, last = period_bounds(day, granularity)
        span = "" if granularity == "day" else f" – {last:%d %b %Y}"
        return f"{day:%d %b %Y}{span}\n{count:,} photos"

    def _layout(self) -> None:
        """Bars are contiguous: this is a histogram over time, not a bar chart."""
        self._bars.clear()
        if not self.timeline or not self.timeline.points:
            return
        top, bottom = PADDING, self.height() - LABEL_HEIGHT - PADDING
        span = self.width() - PADDING * 2
        count = len(self.timeline.points)
        step = span / max(count, 1)
        width = max(BAR_MIN_WIDTH, step - GAP)
        # Photo libraries are long-tailed: one imported month can hold a
        # thousand frames while most months hold a handful. Scaled to the peak
        # that flattens every ordinary month to one or two pixels and the chart
        # reads as a flat line. A square root keeps the ordering and the shape
        # recognisable while making the small months visible; the exact counts
        # are in the tooltip, so nothing is hidden by the softer scale.
        peak = max(count for _day, count in self.timeline.points) or 1
        room = bottom - top
        for index, (day, count) in enumerate(self.timeline.points):
            x = PADDING + index * step
            height = room * (count / peak) ** 0.5
            height = max(MIN_BAR, height)
            self._bars.append((day, QRectF(x, bottom - height, width, height)))

    def resizeEvent(self, event) -> None:  # noqa: D102, N802
        self._layout()
        super().resizeEvent(event)

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: D102, N802
        painter = QPainter(self)
        try:
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.timeline or not self._bars:
            painter.setPen(QColor(self.theme.text_faint))
            painter.drawText(self.rect(), Qt.AlignCenter, "No photos to chart yet")
            return

        baseline = self.height() - LABEL_HEIGHT
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self.theme.bar_bg))
        painter.drawRect(QRectF(PADDING, baseline, self.width() - PADDING * 2, 1))

        selected_from, selected_to = self.selection
        for position, (day, rect) in enumerate(self._bars):
            inside = (
                (selected_from is None or day >= selected_from)
                and (selected_to is None or day <= selected_to)
                and (selected_from is not None or selected_to is not None)
            )
            painter.setPen(Qt.NoPen)
            if inside:
                colour = self.theme.accent
            elif position == self._hover:
                # Brighter than the resting bars, so the pointer's period is
                # obvious before the tooltip even appears.
                colour = QColor(self.theme.accent_dim).lighter(135).name()
            else:
                colour = self.theme.accent_dim
            painter.setBrush(QColor(colour))
            painter.drawRoundedRect(rect, 2.5, 2.5)

        painter.setPen(QColor(self.theme.text_faint))
        font = painter.font()
        font.setPointSizeF(max(6.5, font.pointSizeF() - 1))
        painter.setFont(font)
        metrics = QFontMetrics(font)
        granularity = self.timeline.granularity
        baseline = self.height() - LABEL_HEIGHT
        last_x = -100.0
        for day, rect in self._bars:
            is_boundary = rect.x() < 2 or rect.right() > self.width() - 2
            if not is_boundary and day.day != 1:
                continue
            x = rect.x() - 4
            if x - last_x < 52:  # avoid overlapping tick labels
                continue
            last_x = x
            painter.drawText(
                QRectF(x, baseline, 52, LABEL_HEIGHT - 2),
                Qt.AlignLeft, metrics.elidedText(_tick_label(day, granularity), Qt.ElideRight, 52),
            )

    # -- interaction -------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: D102, N802
        if not self._bars:
            return
        self._dragging = True
        self._anchor = self._index_at(event.position().x())
        self._emit_selection()

    def mouseMoveEvent(self, event) -> None:  # noqa: D102, N802
        x = event.position().x()
        if self._dragging:
            self._emit_selection(x)
        else:
            # Hovering has to say what a period holds. The tooltip text was
            # written but nothing ever asked for it, so the dates chart showed
            # bars and no titles at all.
            self._set_hover(self._index_at(x))
            self.setToolTip(self.tooltip_for(x))

    def leaveEvent(self, event) -> None:  # noqa: D102, N802
        # Drop the tooltip too, or it sticks to the cursor position and
        # describes a period the pointer is no longer over.
        self._set_hover(None)
        self.setToolTip("")
        super().leaveEvent(event)

    def _set_hover(self, index: int | None) -> None:
        if index != self._hover:
            self._hover = index
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: D102, N802
        if not self._dragging:
            return
        self._dragging = False
        width = abs(event.position().x() - self._bar_x(self._anchor))
        if width < 4:
            # A click without a drag clears the date filter.
            self.selection = (None, None)
            self.cleared.emit()
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: D102, N802
        self.selection = (None, None)
        self.cleared.emit()
        self.update()

    def _emit_selection(self, position: float | None = None) -> None:
        if not self._bars:
            return
        # The anchor is captured on press, and the bars are rebuilt whenever the
        # data changes, so between the two a drag can arrive with an anchor
        # pointing past the end — which is how this used to throw IndexError on
        # every mouse move, and how one stray exception ended up looking like a
        # dead button. Clamp rather than trust.
        last = len(self._bars) - 1
        anchor = max(0, min(self._anchor, last))
        index = anchor if position is None else max(0, min(self._index_at(position), last))
        low, high = min(anchor, index), max(anchor, index)
        self.selection = (self._bars[low][0], self._bars[high][0])
        self.update()
        self.range_selected.emit(*self.selection)

    def _bar_x(self, index: int) -> float:
        rect = self._bars[max(0, min(index, len(self._bars) - 1))][1]
        return rect.center().x()

    def _index_at(self, x: float) -> int:
        if not self._bars:
            return 0
        best, distance = 0, float("inf")
        for index, (_day, rect) in enumerate(self._bars):
            centre = rect.center().x()
            if abs(centre - x) < distance:
                best, distance = index, abs(centre - x)
        return best


def _tick_label(day: date, granularity: str) -> str:
    if granularity == "year":
        return str(day.year)
    if granularity == "month":
        return day.strftime("%b %Y")
    if granularity == "week":
        return day.strftime("%d %b")
    return day.strftime("%d %b")


def period_bounds(day: date, granularity: str) -> tuple[date, date]:
    """First and last day of the period a point represents."""
    if granularity == "year":
        return date(day.year, 1, 1), date(day.year, 12, 31)
    if granularity == "month":
        next_month = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
        return day, next_month - timedelta(days=1)
    if granularity == "week":
        return day, day + timedelta(days=6)
    return day, day
