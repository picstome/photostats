"""The filter sidebar: date range, numeric ranges and value lists."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.filters import (
    FACET_APERTURE,
    FACET_CAMERA,
    FACET_FOCAL,
    FACET_ISO,
    FACET_LENS,
    FLASH_ANY,
    FLASH_FIRED,
    FLASH_NOT_FIRED,
    Filter,
)
from ...core.parse import format_fnumber, format_focal, format_shutter
from ...i18n import tr
from ..components.card import Section
from ..components.check_list import CheckList
from ..components.range_slider import RangeSlider

#: (label, fraction) pairs drawn under the shutter slider.
#: Tick labels under each slider, as (text, position 0-1 along the track).
#: ISO in published third-stop steps. Written out rather than computed: rounding
#: a float recurrence drifts into values no camera has, like "4 034".
ISO_SERIES = (
    25, 32, 40, 50, 63, 80, 100, 125, 160, 200, 250, 320, 400, 500, 640, 800,
    1000, 1250, 1600, 2000, 2500, 3200, 4000, 5000, 6400, 8000, 10000, 12800,
    16000, 20000, 25600, 32000, 40000, 51200, 64000, 80000, 102400, 128000,
    160000, 204800, 256000,
)


#: The f-numbers a lens actually has, in third stops.
APERTURE_SERIES = (1.0, 1.2, 1.4, 1.8, 2.0, 2.8, 4.0, 5.6, 8.0, 11.0, 16.0,
                   22.0, 32.0)


#: Shutter speeds in published third-stop steps, 1/8000 up to 30s.
#: Built from the denominators rather than written as reciprocals: a rounded
#: 1/6400 comes back out of format_shutter as "1/6410".
SHUTTER_SERIES = tuple(
    [1 / d for d in (8000, 6400, 5000, 4000, 3200, 2500, 2000, 1600, 1250,
                      1000, 800, 640, 500, 400, 320, 250, 200, 160, 125, 100,
                      80, 60, 50, 40, 30, 25, 20, 15, 13, 10, 8, 6, 5, 4, 3, 2)]
    + [0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.3, 1.6, 2.0, 2.5, 3.2, 4.0, 5.0, 6.0,
       8.0, 10.0, 13.0, 15.0, 20.0, 25.0, 30.0]
)


#: Common focal lengths.
FOCAL_SERIES = (8, 10, 12, 14, 16, 18, 20, 24, 28, 35, 40, 50, 60, 70, 85, 100,
                120, 135, 150, 180, 200, 240, 300, 400, 500, 600, 800, 1000, 1200)


#: Tick marks come from these, so a label is always a number that exists as a
#: real setting rather than an even fraction of the track.
FACET_TICKS = {
    FACET_ISO: ISO_SERIES,
    "shutter": SHUTTER_SERIES,
    FACET_APERTURE: APERTURE_SERIES,
    FACET_FOCAL: FOCAL_SERIES,
}

#: How each numeric facet is written in the sidebar.
FACET_FORMATTERS = {
    FACET_ISO: lambda value: f"{value:,.0f}".replace(",", " "),
    "shutter": lambda value: format_shutter(value),
    FACET_APERTURE: lambda value: format_fnumber(value),
    FACET_FOCAL: lambda value: format_focal(value),
}

DEFAULT_BOUNDS = {
    FACET_ISO: (50.0, 204800.0),
    "shutter": (0.0001, 30.0),
    FACET_APERTURE: (0.7, 64.0),
    FACET_FOCAL: (8.0, 1200.0),
}


class _CalendarDateEdit(QDateEdit):
    """A date field where a click anywhere opens the calendar.

    A click on the text (not just the small drop-down arrow) pops the calendar,
    which is what a date field is expected to do.

    The popup is themed here as well: Qt paints the weekend columns red and the
    header in the default palette, neither of which is this app's palette, and
    those are per-column *formats* rather than stylesheet properties.
    """

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setCalendarPopup(True)
        self._apply_calendar_theme()

    def _apply_calendar_theme(self) -> None:
        calendar = self.calendarWidget()
        if calendar is None:
            return
        calendar.setGridVisible(False)

        header = QTextCharFormat()
        header.setForeground(QColor(self.theme.text))
        header.setFontWeight(QFont.DemiBold)
        calendar.setHeaderTextFormat(header)

        # Weekdays in the muted tone, weekends only a touch fainter: the
        # distinction stays legible without the default red.
        weekday = QTextCharFormat()
        weekday.setForeground(QColor(self.theme.text_dim))
        for day in (Qt.Monday, Qt.Tuesday, Qt.Wednesday, Qt.Thursday, Qt.Friday):
            calendar.setWeekdayTextFormat(day, weekday)
        weekend = QTextCharFormat()
        weekend.setForeground(QColor(self.theme.text_faint))
        for day in (Qt.Saturday, Qt.Sunday):
            calendar.setWeekdayTextFormat(day, weekend)

        # Today reads as the accent, but a selected day keeps the accent
        # background and its own light text, so this is only a foreground.
        today = QTextCharFormat()
        today.setForeground(QColor(self.theme.accent))
        today.setFontWeight(QFont.Bold)
        calendar.setDateTextFormat(QDate.currentDate(), today)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self._popup_calendar()

    def _popup_calendar(self) -> None:
        calendar = self.calendarWidget()
        if calendar is None:
            return
        popup = calendar.parentWidget()
        if popup is None:
            return
        popup.move(self.mapToGlobal(self.rect().bottomLeft()))
        popup.show()


class FilterPanel(QWidget):
    """Builds a :class:`Filter` and reports changes; never touches the database."""

    filters_changed = Signal(object)   # Filter
    clear_requested = Signal()
    preset_requested = Signal(str)     # 'this_year' | 'last_12' | 'last_30' | 'all'

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.filters = Filter()
        self._loading = False
        self._bounds = dict(DEFAULT_BOUNDS)
        #: The date pickers' resting values: the library's oldest day and today.
        #: Resting on the oldest day (or on today) means "no bound", so the
        #: pickers read as real dates instead of placeholder years without
        #: filtering anything. Replaced from the library once it is known.
        self._date_defaults: tuple[date, date] = (date(2000, 1, 1), date.today())
        #: The clear button is built last; handlers must tolerate its absence.
        self.clear_button: QPushButton | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 12, 12, 14)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel(tr("Filters"))
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        header.addWidget(title)
        header.addStretch(1)
        self.badge = QLabel("")
        self.badge.setObjectName("hint")
        header.addWidget(self.badge)
        layout.addLayout(header)

        # Cameras and lenses first: they are what people filter by most, and
        # they sit at the top where they are visible without scrolling. Cameras
        # starts open — it is the facet a photographer reaches for first, and a
        # panel that is always there is faster than one more click.
        layout.addWidget(self._build_list_section(
            FACET_CAMERA, tr("Cameras"), tr("Search cameras…"), expanded=True))
        layout.addWidget(self._build_list_section(FACET_LENS, tr("Lenses"), tr("Search lenses…")))
        layout.addWidget(self._build_slider_section(FACET_ISO, tr("ISO"), log=True, tick_count=4))
        layout.addWidget(self._build_slider_section("shutter", tr("Shutter"), log=True,
                                    tick_count=5))
        layout.addWidget(
            self._build_slider_section(FACET_APERTURE, tr("Aperture"), log=False,
                                       tick_count=4)
        )
        layout.addWidget(
            self._build_slider_section(FACET_FOCAL, tr("Focal length"), log=True,
                                       tick_count=4)
        )
        layout.addWidget(self._build_flash_section())
        layout.addWidget(self._build_date_section())

        layout.addStretch(1)

        button = QPushButton(tr("Clear all filters"))
        button.setObjectName("secondary")
        button.clicked.connect(self._on_clear)
        layout.addWidget(button)
        self.clear_button = button

    # -- sections ----------------------------------------------------------
    def _build_date_section(self) -> Section:
        section = Section(self.theme, tr("Date"))
        section.header.setChecked(False)
        section.body.setVisible(False)
        presets = QHBoxLayout()
        presets.setSpacing(4)
        for label, key in (("This year", "this_year"), ("12 months", "last_12"),
                           ("30 days", "last_30"), ("All", "all")):
            button = QPushButton(label)
            button.setObjectName("chipButton")
            button.clicked.connect(lambda _c=False, k=key: self.preset_requested.emit(k))
            presets.addWidget(button)
        section.body_layout.addLayout(presets)

        # One picker per line: two side by side do not fit a 300px sidebar.
        for caption, attribute in (("from", "date_from"), ("to", "date_to")):
            row = QHBoxLayout()
            row.setSpacing(6)
            label = QLabel(caption)
            label.setFixedWidth(34)
            label.setObjectName("hint")
            edit = _CalendarDateEdit(self.theme)
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.setObjectName("secondary")
            edit.setDate(QDate(
                self._date_defaults[0] if attribute == "date_from"
                else self._date_defaults[1]))
            edit.dateChanged.connect(self._on_date_changed)
            setattr(self, attribute, edit)
            row.addWidget(label)
            row.addWidget(edit, 1)
            section.body_layout.addLayout(row)

        self.include_no_date = QCheckBox("Include photos with no EXIF date")
        self.include_no_date.setToolTip(
            "Photos without a capture date fall back to the file's modification date"
        )
        self.include_no_date.toggled.connect(self._on_no_date_toggled)
        section.body_layout.addWidget(self.include_no_date)
        return section

    def _build_slider_section(self, facet: str, title: str, log: bool,
                              tick_count: int = 4) -> Section:
        section = Section(self.theme, title)
        section.header.setChecked(False)
        section.body.setVisible(False)
        low, high = self._bounds[facet]
        slider = RangeSlider(
            self.theme, low, high, log=log,
            tick_values=FACET_TICKS.get(facet, ()),
            tick_count=tick_count,
            formatter=FACET_FORMATTERS[facet],
        )
        slider.changed.connect(lambda lo, hi, f=facet: self._on_range(f, lo, hi))
        section.body_layout.addWidget(slider)

        readout = QLabel("")
        readout.setObjectName("hint")
        section.body_layout.addWidget(readout)

        setattr(self, f"slider_{facet}", slider)
        setattr(self, f"readout_{facet}", readout)
        return section

    def _build_list_section(self, facet: str, title: str, placeholder: str,
                            expanded: bool = False) -> Section:
        section = Section(self.theme, title)
        section.set_expanded(expanded)
        checklist = CheckList(self.theme, placeholder)
        checklist.selection_changed.connect(lambda values, f=facet: self._on_values(f, values))
        section.body_layout.addWidget(checklist)
        setattr(self, f"list_{facet}", checklist)
        return section

    def _build_flash_section(self) -> Section:
        section = Section(self.theme, tr("Flash"))
        section.header.setChecked(False)
        section.body.setVisible(False)
        group = QButtonGroup(self)
        group.setExclusive(True)
        self.flash_any = QRadioButton("Any")
        self.flash_fired = QRadioButton("Fired")
        self.flash_none = QRadioButton("Not fired")
        for index, button in enumerate((self.flash_any, self.flash_fired, self.flash_none)):
            group.addButton(button, index)
            section.body_layout.addWidget(button)
            button.toggled.connect(self._on_flash_toggled)
        self.flash_any.setChecked(True)
        return section

    # -- feeding data ------------------------------------------------------
    def set_bounds(self, ranges: dict) -> None:
        """Scale each slider to the values actually in the library.

        The handles span exactly the lowest and highest value present — the
        lowest ISO anyone shot and the highest — rather than some fixed range,
        so the whole track is meaningful and a double-click restores it exactly.
        """
        for facet, key in ((FACET_ISO, "iso"), ("shutter", "shutter"),
                           (FACET_APERTURE, "aperture"), (FACET_FOCAL, "focal")):
            observed = ranges.get(key)
            if not observed or observed[0] is None:
                continue
            low, high = observed
            if low is None or high is None:
                continue
            if high <= low:
                high = low * 2 if key != "aperture" else low + 1
            slider = getattr(self, f"slider_{facet}", None)
            if slider is None:
                continue
            slider.set_bounds(float(low), float(high))
            slider.reset()

        # The date pickers rest on the library's oldest day and on today, and
        # neither may be dragged into the future: a capture date after today is
        # a camera clock that was wrong, not a day worth filtering to.
        observed = ranges.get("date")
        today = date.today()
        oldest = observed[0] if observed and observed[0] else date(2000, 1, 1)
        if oldest > today:
            oldest = today
        self._date_defaults = (oldest, today)
        self._loading = True
        try:
            for edit in (self.date_from, self.date_to):
                edit.setMinimumDate(QDate(oldest))
                edit.setMaximumDate(QDate(today))
        finally:
            self._loading = False

    def clear(self) -> None:
        """Empty every list and reset the controls.

        Used when the library is closed out, so the sidebar cannot keep offering
        values from a folder that is no longer open.
        """
        self._loading = True
        try:
            self.filters = Filter()
            for facet in (FACET_CAMERA, FACET_LENS):
                checklist = getattr(self, f"list_{facet}", None)
                if checklist is not None:
                    checklist.set_values([])
            for name in ("iso", "shutter", "aperture", "focal"):
                getattr(self, f"slider_{name}").reset()
            for name, value in (("date_from", self._date_defaults[0]),
                                ("date_to", self._date_defaults[1])):
                getattr(self, name).setDate(QDate(value))
            self.flash_any.setChecked(True)
            self.include_no_date.setChecked(False)
        finally:
            self._loading = False
        self._update_badge()
        self._refresh_readouts()

    def set_values(self, facet: str, values: list[tuple[str, int, float]]) -> None:
        """Populate a facet's value list from the database."""
        checklist = getattr(self, f"list_{facet}", None)
        if checklist is not None:
            attribute = "cameras" if facet == FACET_CAMERA else "lenses"
            checklist.set_values(values, set(getattr(self.filters, attribute)))

    def set_list_selection(self, facet: str, selected: set[str]) -> None:
        checklist = getattr(self, f"list_{facet}", None)
        if checklist is not None:
            checklist.set_selected(selected)

    def apply(self, filters: Filter) -> None:
        """Reflect a filter without re-emitting a change."""
        self._loading = True
        self.filters = filters
        try:
            self.set_list_selection(FACET_CAMERA, set(filters.cameras))
            self.set_list_selection(FACET_LENS, set(filters.lenses))
            for facet, low_attr, high_attr in (
                (FACET_ISO, "iso_min", "iso_max"),
                ("shutter", "shutter_min", "shutter_max"),
                (FACET_APERTURE, "aperture_min", "aperture_max"),
                (FACET_FOCAL, "focal_min", "focal_max"),
            ):
                slider = getattr(self, f"slider_{facet}")
                low, high = getattr(filters, low_attr), getattr(filters, high_attr)
                slider.set_range(low, high)
                readout = getattr(self, f"readout_{facet}")
                left, right = slider.display_range()
                full = slider.is_full()
                readout.setText(f"{left} – {right}" + ("" if full else "  " + tr("(filtered)")))
            self.date_from.blockSignals(True)
            self.date_to.blockSignals(True)
            self.date_from.setDate(
                QDate(filters.date_from) if filters.date_from
                else QDate(self._date_defaults[0])
            )
            self.date_to.setDate(
                QDate(filters.date_to) if filters.date_to
                else QDate(self._date_defaults[1])
            )
            self.date_from.blockSignals(False)
            self.date_to.blockSignals(False)
            self.include_no_date.blockSignals(True)
            self.include_no_date.setChecked(filters.include_no_date)
            self.include_no_date.blockSignals(False)
            self.flash_any.setChecked(filters.flash == FLASH_ANY)
            self.flash_fired.setChecked(filters.flash == FLASH_FIRED)
            self.flash_none.setChecked(filters.flash == FLASH_NOT_FIRED)
            self._refresh_readouts()
            self._update_badge()
        finally:
            self._loading = False

    # -- events ------------------------------------------------------------
    def _emit(self) -> None:
        if self._loading:
            return
        self._update_badge()
        self.filters_changed.emit(self.filters)

    def _refresh_readouts(self) -> None:
        """Redraw the slider captions after the scale changes."""
        for facet in (FACET_ISO, "shutter", FACET_APERTURE, FACET_FOCAL):
            slider = getattr(self, f"slider_{facet}", None)
            readout = getattr(self, f"readout_{facet}", None)
            if slider is None or readout is None:
                continue
            left, right = slider.display_range()
            readout.setText(f"{left} – {right}" + ("" if slider.is_full() else "  " + tr("(filtered)")))

    def _on_range(self, facet: str, low, high) -> None:
        slider = getattr(self, f"slider_{facet}")
        # Both handles at the ends is the whole range, which is the same as no
        # filter at all. Recording it as one would filter nothing while
        # claiming to filter, and the chip would say otherwise.
        self.filters = _with_range(
            self.filters, facet,
            None if slider.is_full() else low,
            None if slider.is_full() else high,
        )
        left, right = slider.display_range()
        readout = getattr(self, f"readout_{facet}")
        readout.setText(f"{left} – {right}" + ("" if slider.is_full() else "  " + tr("(filtered)")))
        self._emit()

    def _on_values(self, facet: str, values: list[str]) -> None:
        if self._loading:
            return
        attribute = "cameras" if facet == FACET_CAMERA else "lenses"
        self.filters = _with_values(self.filters, attribute, values)
        self._emit()

    def _on_date_changed(self) -> None:
        if self._loading:
            return
        start = self.date_from.date().toPython()
        end = self.date_to.date().toPython()
        # Resting on the default ends means "no bound": the pickers show the
        # library's real span, but they only filter once moved inside it.
        default_from, default_to = self._date_defaults
        if start <= default_from:
            start = None
        if end >= default_to:
            end = None
        self.filters = _with_values(self.filters, "date_from", start)
        self.filters = _with_values(self.filters, "date_to", end)
        self._emit()

    def _on_no_date_toggled(self, checked: bool) -> None:
        self.filters = _with_values(self.filters, "include_no_date", checked)
        self._emit()

    def _on_flash_toggled(self, checked: bool) -> None:
        if not checked or self._loading:
            return
        if self.flash_fired.isChecked():
            value = FLASH_FIRED
        elif self.flash_none.isChecked():
            value = FLASH_NOT_FIRED
        else:
            value = FLASH_ANY
        self.filters = _with_values(self.filters, "flash", value)
        self._emit()

    def _on_clear(self) -> None:
        self.apply(Filter(include_no_date=self.filters.include_no_date))
        self.filters = Filter(include_no_date=self.filters.include_no_date)
        self._emit()
        self.clear_requested.emit()

    def _update_badge(self) -> None:
        count = self.filters.active_count
        self.badge.setText(tr("{count} active", count=count) if count else "")
        if self.clear_button is not None:
            self.clear_button.setEnabled(bool(count))


_RANGE_ATTRIBUTES = {
    FACET_ISO: ("iso_min", "iso_max"),
    "shutter": ("shutter_min", "shutter_max"),
    FACET_APERTURE: ("aperture_min", "aperture_max"),
    FACET_FOCAL: ("focal_min", "focal_max"),
}


def _with_range(filters: Filter, facet: str, low, high) -> Filter:
    low_attr, high_attr = _RANGE_ATTRIBUTES[facet]
    return replace(filters, **{low_attr: low, high_attr: high})


def _with_values(filters: Filter, attribute: str, value) -> Filter:
    return replace(filters, **{attribute: frozenset(value) if attribute in _SET_ATTRS else value})


_SET_ATTRS = {"cameras", "lenses"}
