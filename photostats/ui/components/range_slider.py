"""Dual-handle range slider with an optional logarithmic scale.

Used for ISO, shutter speed, aperture and focal length, whose useful ranges span
orders of magnitude. Handles are keyboard accessible and can be dragged together.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

TRACK_HEIGHT = 6
HANDLE_RADIUS = 9
HEIGHT = 44
PADDING = HANDLE_RADIUS + 4


class RangeSlider(QWidget):
    """Two handles defining [low, high]; either may be unset (None)."""

    changed = Signal(object, object)  # (low, high) — may be None
    released = Signal()

    def __init__(self, theme, minimum: float, maximum: float, log: bool = False,
                 tick_values: Sequence[float] = (), tick_count: int = 4,
                 formatter=None, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.minimum = minimum
        self.maximum = maximum
        self.log = log
        #: How to write a value for people: ISO is plain, f-stops are not.
        self.formatter = formatter or (lambda value: f"{value:g}")
        #: Candidate values in ascending order, e.g. the ISO series. Ticks are
        #: picked from these so the labels are numbers a photographer recognises.
        self.tick_values = tuple(sorted(tick_values))
        self._tick_count = tick_count
        self.low: float | None = minimum
        self.high: float | None = maximum
        self._dragging: str | None = None
        self._drag_start = 0.0
        self._low_at_start = 0.0
        self._high_at_start = 0.0
        self.setFixedHeight(HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.ArrowCursor)

    # -- scale -------------------------------------------------------------
    def _to_position(self, value: float) -> float:
        if self.maximum <= self.minimum:
            return 0.0
        if self.log:
            low = max(self.minimum, 1e-6)
            value = max(low, value)
            span = _log(self.maximum) - _log(low)
            if span <= 0:
                return 0.0
            fraction = (_log(value) - _log(low)) / span
        else:
            fraction = (value - self.minimum) / (self.maximum - self.minimum)
        return PADDING + fraction * (self.width() - 2 * PADDING)

    def _to_value(self, position: float) -> float:
        span = self.width() - 2 * PADDING
        if span <= 0:
            return self.minimum
        fraction = max(0.0, min(1.0, (position - PADDING) / span))
        if self.log:
            low = max(self.minimum, 1e-6)
            value = _exp(_log(low) + fraction * (_log(self.maximum) - _log(low)))
        else:
            value = self.minimum + fraction * (self.maximum - self.minimum)
        return _round(value, self.log)

    def _from_fraction(self, fraction: float) -> float:
        """The value at *fraction* along the track: the inverse of _to_value."""
        if self.log:
            low = max(self.minimum, 1e-6)
            value = _exp(_log(low) + fraction * (_log(self.maximum) - _log(low)))
        else:
            value = self.minimum + fraction * (self.maximum - self.minimum)
        return _round(value, self.log)

    # -- state -------------------------------------------------------------
    def set_range(self, low: float | None, high: float | None, emit: bool = False) -> None:
        self.low = None if low is None else max(self.minimum, min(low, self.maximum))
        self.high = None if high is None else max(self.minimum, min(high, self.maximum))
        if self.low is not None and self.high is not None and self.low > self.high:
            self.low, self.high = self.high, self.low
        self.update()
        if emit:
            self.changed.emit(self.low, self.high)

    def set_bounds(self, minimum: float, maximum: float) -> None:
        """Scale the track to the values the library actually contains."""
        if maximum <= minimum:
            return
        self.minimum, self.maximum = minimum, maximum
        if self.low is not None:
            self.low = max(minimum, self.low)
        if self.high is not None:
            self.high = min(maximum, self.high)
        self.update()

    def is_full(self) -> bool:
        return (self.low is None or self.low <= self.minimum) and (
            self.high is None or self.high >= self.maximum
        )

    def reset(self, emit: bool = False) -> None:
        """Return both handles to the ends of the track.

        Silent by default, because the internal caller rescales the track when a
        library's real range is discovered and must not look like a user
        choosing that range: doing so produced four filter chips and "8 active"
        on a library with nothing filtered. The double-click and the Home key
        pass emit=True, so a real reset also clears the filter.
        """
        if emit:
            self.low = self.high = None
            self.update()
            self.changed.emit(None, None)
        else:
            self.set_range(self.minimum, self.maximum, emit=False)

    def tick_labels(self) -> list[tuple[float, str]]:
        """Evenly spaced marks labelled with real values from this track.

        Computed from the current bounds rather than baked in: the track spans
        the library's own ISO or shutter range, so a fixed table of labels would
        sit under the wrong numbers.
        """
        if self.maximum <= self.minimum:
            return []
        # The two ends are always labelled truthfully, even when the library's
        # extremes are not standard settings.
        values = [self.minimum]
        interior = [v for v in self.tick_values
                    if self.minimum < v < self.maximum]
        budget = max(0, self._tick_count - 1)
        if budget == 0:
            interior = []
        elif len(interior) > budget:
            # Choose by where a label would sit on the track, not by index: the
            # ladders are log-spaced, so index spacing crowds the ends.
            interior = sorted(
                min(interior,
                    key=lambda value: abs(self._fraction_of(value) - target))
                for target in (
                    (i + 1) / (budget + 1) for i in range(budget)
                )
            )
        values.extend(interior)
        values.append(self.maximum)
        return sorted(
            ((self._fraction_of(value), self.formatter(value)) for value in values),
            key=lambda pair: pair[0],
        )

    def _fraction_of(self, value: float) -> float:
        """Where *value* sits along the track, as a 0-1 fraction."""
        if self.maximum <= self.minimum:
            return 0.0
        if self.log:
            low = max(self.minimum, 1e-6)
            span = _log(self.maximum) - _log(low)
            if span <= 0:
                return 0.0
            return (_log(max(low, value)) - _log(low)) / span
        return (value - self.minimum) / (self.maximum - self.minimum)

    def display_range(self) -> tuple[str, str]:
        """The selected bounds, written the way a photographer would."""
        low = self.minimum if self.low is None else self.low
        high = self.maximum if self.high is None else self.high
        return self.formatter(low), self.formatter(high)

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: D102, N802
        painter = QPainter(self)
        try:
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        left, right = self._to_position(self.minimum), self._to_position(self.maximum)
        mid = self.height() / 2 - 3

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self.theme.bar_bg))
        painter.drawRoundedRect(QRectF(left, mid, right - left, TRACK_HEIGHT), 3, 3)

        low_x = left if self.low is None else self._to_position(self.low)
        high_x = right if self.high is None else self._to_position(self.high)
        if high_x > low_x:
            painter.setBrush(QColor(self.theme.accent))
            painter.drawRoundedRect(QRectF(low_x, mid, high_x - low_x, TRACK_HEIGHT), 3, 3)

        if self.hasFocus():
            painter.setPen(QPen(QColor(self.theme.accent), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)

        for value, is_active in ((low_x, True), (high_x, False)):
            colour = QColor(self.theme.accent if is_active else self.theme.text_dim)
            painter.setBrush(colour)
            painter.setPen(QPen(QColor(self.theme.card), 2))
            painter.drawEllipse(QPointF(value, mid + TRACK_HEIGHT / 2), HANDLE_RADIUS,
                                HANDLE_RADIUS)

        if self.tick_labels():
            painter.setPen(QColor(self.theme.text_faint))
            font = painter.font()
            font.setPointSizeF(max(6.5, font.pointSizeF() - 1))
            painter.setFont(font)
            metrics = QFontMetrics(font)
            for fraction, text in self.tick_labels():
                x = left + fraction * (right - left)
                elided = metrics.elidedText(text, Qt.ElideRight, 54)
                painter.drawText(
                    QRectF(x - 27, self.height() - 13, 54, 12),
                    Qt.AlignCenter, elided,
                )

    # -- interaction -------------------------------------------------------
    def _which(self, position: float) -> str | None:
        track_left = self._to_position(self.minimum)
        track_right = self._to_position(self.maximum)
        low_x = track_left if self.low is None else self._to_position(self.low)
        high_x = track_right if self.high is None else self._to_position(self.high)
        if abs(position - low_x) <= HANDLE_RADIUS:
            return "low"
        if abs(position - high_x) <= HANDLE_RADIUS:
            return "high"
        if track_left <= position <= track_right:
            return "track"
        return None

    def mousePressEvent(self, event) -> None:  # noqa: D102, N802
        self._dragging = self._which(event.position().x())
        self._drag_start = event.position().x()
        self._low_at_start = self.low if self.low is not None else self.minimum
        self._high_at_start = self.high if self.high is not None else self.maximum
        self.setFocus(Qt.MouseFocusReason)
        if self._dragging:
            self._apply(event.position().x())

    def mouseMoveEvent(self, event) -> None:  # noqa: D102, N802
        if not self._dragging:
            self.setCursor(
                Qt.SizeHorCursor if self._which(event.position().x()) else Qt.ArrowCursor
            )
            return
        if self._dragging == "track" and abs(event.position().x() - self._drag_start) > 3:
            self._dragging = "track"  # keep moving the pair together
        self._apply(event.position().x())

    def mouseReleaseEvent(self, event) -> None:  # noqa: D102, N802
        if self._dragging:
            self._apply(event.position().x())
        self._dragging = None
        self.released.emit()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: D102, N802
        self.reset(emit=True)

    def wheelEvent(self, event) -> None:  # noqa: D102, N802
        """Scroll the whole window (and zoom the range) over the slider."""
        event.ignore()

    def keyPressEvent(self, event) -> None:  # noqa: D102, N802
        if event.key() == Qt.Key_Left:
            self._nudge(-1, +1)
        elif event.key() == Qt.Key_Right:
            self._nudge(+1, -1)
        elif event.key() == Qt.Key_Home:
            self.set_range(self.minimum, self.high, emit=True)
        elif event.key() == Qt.Key_End:
            self.set_range(self.low, self.maximum, emit=True)
        elif event.key() in (Qt.Key_Backspace, Qt.Key_Delete):
            self.reset(emit=True)
        else:
            super().keyPressEvent(event)

    def _nudge(self, low_step: int, high_step: int) -> None:
        """Move each handle by *low_step* / *high_step* notches.

        A logarithmic track moves by a factor, not a fixed amount: adding 26 to
        an 8mm handle and to a 1600mm one are not the same step, and the fixed
        step was so coarse on a wide focal range that the arrows were useless.
        A linear track keeps a plain one-percent step.
        """
        low = self.low if self.low is not None else self.minimum
        high = self.high if self.high is not None else self.maximum
        if self.log:
            factor = 1.1 ** low_step
            new_low = _round(low * factor, True)
            new_high = _round(high * (1.1 ** high_step), True)
        else:
            unit = (self.maximum - self.minimum) / 100
            new_low = _round(low + unit * low_step, False)
            new_high = _round(high + unit * high_step, False)
        if new_low > new_high:
            new_low, new_high = new_high, new_low
        self.set_range(
            None if self.low is None and new_low <= self.minimum else new_low,
            None if self.high is None and new_high >= self.maximum else new_high,
            emit=True,
        )

    def _apply(self, position: float) -> None:
        value = self._to_value(position)
        if self._dragging == "low":
            self.set_range(min(value, self.high if self.high is not None else self.maximum),
                           self.high, emit=True)
        elif self._dragging == "high":
            self.set_range(self.low,
                           max(value, self.low if self.low is not None else self.minimum),
                           emit=True)
        elif self._dragging == "track":
            shift = self._to_value(position) - self._to_value(self._drag_start)
            span = self._high_at_start - self._low_at_start
            low = max(self.minimum, min(self._low_at_start + shift, self.maximum - span))
            self.set_range(_round(low, self.log), _round(low + span, self.log), emit=True)


def _log(value: float) -> float:
    import math

    return math.log(max(value, 1e-9))


def _exp(value: float) -> float:
    import math

    return math.exp(value)


def _round(value: float, log: bool) -> float:
    if value <= 0:
        return value
    if log:
        # Snap to photographer-friendly values instead of 137.42.
        from ...core.parse import STANDARD_SHUTTERS

        if 0.0005 < value < 1:
            best = min(STANDARD_SHUTTERS, key=lambda d: abs(1 / d - value))
            if abs(1 / best - value) <= value * 0.08:
                return 1 / best
        return float(f"{value:.4g}")
    if value >= 100:
        return float(int(round(value)))
    return float(f"{value:.1f}")
