"""The statistics area: cross-filterable charts plus the insights line."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.filters import (
    FACET_CAMERA,
    FACET_LENS,
    Filter,
)
from ...core.queries import FACET_TITLES, FacetResult
from ...i18n import tr
from ..components.bar_chart import BarChart
from ..components.card import Card
from ..core_filters_bridge import CHART_FACETS

#: Bars per chart. Deliberately few: a chart that shows everything is harder to
#: read, and the sidebar list is there for the long tail. The card and the chart
#: must agree on this number so bars are never drawn outside the card.
MAX_BARS = 5

#: Narrowest a card may get before the grid drops a column. Sized so the
#: longest realistic camera and lens names still elide rather than truncate.
MIN_CARD_WIDTH = 258

#: Grid chrome: the gap between columns. The grid has no margins of its own —
#: the page supplies the inset — so gaps are the only thing it owns.
GRID_GAP = 12


def columns_for(width: int, wanted: int = 4) -> int:
    """How many columns of at least MIN_CARD_WIDTH fit in *width*.

    The grid carries no margins of its own any more — the page supplies the
    inset — so the whole of *width* is usable, and the answer never exceeds
    what the grid asked for.
    """
    best = 1
    for columns in range(1, wanted + 1):
        if width - GRID_GAP * (columns - 1) >= MIN_CARD_WIDTH * columns:
            best = columns
    return best


class SelectionBadge(QLabel):
    """A pill that names the current bar selection; click it to clear."""

    cleared = Signal()

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("selectionBadge")
        self.setAlignment(Qt.AlignCenter)
        self.setContentsMargins(9, 2, 9, 3)
        self.setVisible(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr("Click to clear this selection"))

    def set_selection(self, values) -> None:
        labels = sorted(values)
        if not labels:
            self.setVisible(False)
            self._values: tuple[str, ...] = ()
            return
        text = labels[0] if len(labels) == 1 else f"{labels[0]} +{len(labels) - 1}"
        self.setText(f"{text}  \u00d7")
        self.setVisible(True)
        self._values = tuple(labels)

    def mousePressEvent(self, event) -> None:  # noqa: D102, N802
        if self._values:
            self.cleared.emit()
        super().mousePressEvent(event)


class ChartCard(Card):
    """Title, total, and a bar chart that reports clicks."""

    bar_clicked = Signal(str, str)  # (facet, label)
    selection_cleared = Signal(str)

    def __init__(self, theme, facet: str, title: str, parent=None) -> None:
        super().__init__(theme, parent)
        self.facet = facet
        #: Translated once at construction; the query layer cannot translate.
        self._title = title
        #: The data currently drawn, kept so callers can inspect it.
        self.result = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        # Hug the content: a chart with three bars should not be as tall as one
        # with eight, which is what happens when the grid stretches every card.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        self.header = QLabel(title)
        self.header.setStyleSheet("font-weight: 600;")
        header_row.addWidget(self.header)
        header_row.addStretch(1)
        # Clicking a bar is silent unless the card says so. This badge names the
        # selection and clears it when clicked.
        self.selection_badge = SelectionBadge(theme)
        header_row.addWidget(self.selection_badge, 0, Qt.AlignTop)
        layout.addLayout(header_row)

        self.selection_badge.cleared.connect(
            lambda: self.selection_cleared.emit(self.facet))

        self.chart = BarChart(theme)
        self.chart.max_bars = MAX_BARS
        self.chart.bar_clicked.connect(lambda label: self.bar_clicked.emit(self.facet, label))
        layout.addWidget(self.chart)

        self.footer = QLabel("")
        self.footer.setObjectName("hint")
        self.footer.setWordWrap(True)
        layout.addWidget(self.footer)

    def set_result(self, result, selected: set[str]) -> None:
        self.result = result
        self.chart.set_result(result, selected)
        visible = len(result.buckets[:MAX_BARS])
        hidden = len(result.buckets) - visible
        parts = [tr("{count} photos", count=f"{result.total:,}")]
        if hidden > 0:
            parts.append(tr("{count} more", count=f"{hidden:,}"))
        if result.unknown:
            parts.append(tr("{count} with no data", count=f"{result.unknown:,}"))
        # The card was named with the translated title; the query only knows
        # the raw one, so keep the name we already translated.
        self.header.setText(self._title if result.title in FACET_TITLES.values()
                             else result.title)
        self.footer.setText(" · ".join(parts))
        self.selection_badge.set_selection(selected)
        self._fit()

    def _fit(self) -> None:
        """Give the card exactly the height it needs.

        Rows are levelled afterwards by :meth:`StatsGrid._level_rows`, so a card
        is free to be as tall as its own content and still end up flush with its
        neighbours.
        """
        self.layout().activate()
        needed = self.sizeHint().height()
        self.setMaximumHeight(needed)
        self.setMinimumHeight(needed)

    def set_empty(self, message: str = "Nothing here yet") -> None:
        self.result = None
        self.chart.clear()
        self.footer.setText(message)
        self.selection_badge.set_selection(set())
        self._fit()

    def selected_values(self) -> set[str]:
        return set(self.chart.selected)


class StatsGrid(QWidget):
    """Chart grid plus the auto-generated insights."""

    bar_clicked = Signal(str, str)
    selection_cleared = Signal(str)

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.cards: dict[str, ChartCard] = {}
        #: Sentences for the insights bar, produced alongside the charts.
        self._insights: list = []
        #: Three abreast, deliberately. Four fits the eight facets into two
        #: exact rows, but it squeezes the name-heavy charts — a lens label
        #: wanted 116px of a 228px card and left the bar 60 — and being able to
        #: read which lens a bar belongs to matters more than an even grid.
        #: The third row holding two cards is the cheaper cost.
        self._columns = 3

        # The page already scrolls (charts_area in the window); nesting another
        # scroll inside the grid gave the grid a margin-plus-scrollbar of its
        # own, so chart cards were narrower than the timeline card above them
        # and nothing lined up. The grid now has no chrome of its own: its
        # margins come from the page, and the widths agree.
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(GRID_GAP)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        for facet in CHART_FACETS:
            card = ChartCard(
                theme, facet, tr(FACET_TITLES.get(facet, facet.title())))
            card.bar_clicked.connect(self.bar_clicked)
            card.selection_cleared.connect(self.selection_cleared)
            # From the token, not a literal: a hardcoded 300 overrode the
            # column calculation and pushed the fourth column off the edge.
            card.setMinimumWidth(MIN_CARD_WIDTH)
            self.cards[facet] = card
        self._reflow()

    # -- layout ------------------------------------------------------------
    def _reflow(self) -> None:
        columns = columns_for(self.width() or 900, self._columns)
        for index, facet in enumerate(CHART_FACETS):
            card = self.cards[facet]
            self.grid.removeWidget(card)
            self.grid.addWidget(card, index // columns, index % columns, Qt.AlignTop)
        for column in range(self._columns + 2):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        self._level_rows(columns)

    def _level_rows(self, columns: int) -> None:
        """Make every card in a row the height of the tallest one in it.

        Sizing each card to its own content left ragged bottoms: a row of three
        came out 151, 151 and 193 pixels tall, and the eye reads the step as
        broken rather than as "this chart has more data".
        """
        self.grid.activate()
        facets = list(self.cards)
        for start in range(0, len(facets), columns):
            row = facets[start:start + columns]
            heights = [self.cards[facet].height() for facet in row]
            tallest = max(heights) if heights else 0
            if not tallest:
                continue
            for facet in row:
                card = self.cards[facet]
                # Tall enough already: capping here would clip the chart.
                if card.height() < tallest:
                    card.setMinimumHeight(tallest)
                    card.setMaximumHeight(tallest)

    def resizeEvent(self, event) -> None:  # noqa: D102, N802
        self._reflow()
        super().resizeEvent(event)

    # -- data --------------------------------------------------------------
    def update_results(self, facets: dict[str, FacetResult], insights: list,
                       filters: Filter) -> None:
        """Apply results the query thread already computed.

        Nothing here queries the database. The facets and the sentences are
        built once on the worker thread (``run_queries``); re-running the eight
        GROUP BYs here would put them back on the GUI thread and freeze the
        window on a large library — the exact thing the background query was
        added to prevent.
        """
        for facet, card in self.cards.items():
            result = facets.get(facet)
            if result is None or result.is_empty:
                card.set_empty(
                    tr("No photos match") if filters.active_count
                    else tr("Nothing to show yet"))
            else:
                selected = _selection_for(filters, facet)
                card.set_result(result, selected)
        self._insights = insights
        self._level_rows(self._active_columns())

    def _active_columns(self) -> int:
        return columns_for(self.width() or 900, self._columns)

    def insights(self) -> list:
        """The sentences built during the last refresh."""
        return self._insights

    def set_selected(self, filters: Filter) -> None:
        for facet, card in self.cards.items():
            card.chart.set_selected(_selection_for(filters, facet))

    def clear(self) -> None:
        for card in self.cards.values():
            card.set_empty("Nothing to show yet")
        self._insights = []


def _selection_for(filters: Filter, facet: str) -> set[str]:
    mapping = {
        FACET_CAMERA: "cameras",
        FACET_LENS: "lenses",
        "white_balance": "white_balance",
        "file_type": "file_types",
    }
    attribute = mapping.get(facet)
    if attribute is None:
        return set()
    return set(getattr(filters, attribute))
