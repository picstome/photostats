"""A separate window listing the photos that match the current filters.

The table used to occupy the bottom half of the main window permanently. Most
sessions never look at it, so it now opens only when asked for, from a button
that states how many photos are on the other side.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...core.format import TYPE_LABELS, WB_LABELS
from ...core.parse import format_fnumber, format_focal, format_shutter
from ...i18n import product_title, tr

COLUMNS = (
    ("File", "name", 230),
    ("Date", "date", 132),
    ("Camera", "camera", 140),
    ("Lens", "lens", 190),
    ("ISO", "iso", 60),
    ("Shutter", "shutter", 78),
    ("Aperture", "aperture", 78),
    ("Focal", "focal", 70),
    ("Flash", "flash", 60),
    ("Type", "type", 64),
)

PAGE_SIZE = 500


class _Model(QAbstractTableModel):
    """Rows fetched a page at a time; sorting is done by the database."""

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.rows: list = []
        self.total = 0

    def set_rows(self, rows, total: int) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.total = total
        self.endResetModel()

    def append_rows(self, rows, total: int) -> None:
        self.set_rows(self.rows + list(rows), total)

    def row_at(self, index: int):
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def rowCount(self, parent=None) -> int:  # noqa: N802
        return 0 if (parent is not None and parent.isValid()) else len(self.rows)

    def columnCount(self, parent=None) -> int:  # noqa: N802
        return 0 if (parent is not None and parent.isValid()) else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            # Translated here rather than at import: the window is rebuilt when
            # the language changes, but the model is shared.
            return tr(COLUMNS[section][0])
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        key = COLUMNS[index.column()][1]
        value = _cell(row, key)
        if role == Qt.DisplayRole:
            return "" if value in (None, "") else str(value)
        if role == Qt.TextAlignmentRole:
            numeric = key in ("iso", "shutter", "aperture", "focal")
            return int(Qt.AlignRight | Qt.AlignVCenter) if numeric else int(
                Qt.AlignLeft | Qt.AlignVCenter
            )
        if role == Qt.ForegroundRole:
            from PySide6.QtGui import QColor

            if key in ("iso", "shutter", "aperture", "focal"):
                return QColor(self.theme.text_dim)
            return QColor(self.theme.text_faint) if value in (None, "") else QColor(
                self.theme.text
            )
        if role == Qt.ToolTipRole:
            return row["rel_path"]
        return None


NUMERIC = {"iso", "shutter", "aperture", "focal"}
SORT_KEYS = {0: "name", 1: "date_desc", 2: "camera", 3: "lens", 4: "iso_desc",
             5: "shutter", 6: "aperture", 7: "focal"}


def _cell(row, key: str):
    if key == "name":
        return row["rel_path"].rsplit("/", 1)[-1]
    if key == "date":
        return (row["taken_at"] or "")[:16]
    if key == "iso":
        return row["iso"] if row["iso"] is not None else ""
    if key == "shutter":
        return format_shutter(row["shutter_seconds"])
    if key == "aperture":
        return format_fnumber(row["fnumber"])
    if key == "focal":
        return format_focal(row["focal_mm"])
    if key == "flash":
        return {1: "Yes", 0: "No"}.get(row["flash_fired"], "—")
    if key == "type":
        return TYPE_LABELS.get(row["file_type"], row["file_type"] or "")
    if key == "wb":
        return WB_LABELS.get(row["white_balance"], row["white_balance"] or "")
    return row[key]


class PhotoListWindow(QMainWindow):
    """Shows the matching photos, paged, with export actions."""

    sort_changed = Signal(str)
    more_requested = Signal()
    revealed = Signal(str)

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setWindowTitle(product_title("matching photos"))
        self.resize(1120, 620)
        self.setStyleSheet(f"QMainWindow {{ background: {theme.bg}; }}")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.headline = QLabel("")
        font = QFont(self.headline.font())
        font.setWeight(QFont.DemiBold)
        self.headline.setFont(font)
        header.addWidget(self.headline)
        header.addStretch(1)

        self.filter_note = QLabel("")
        self.filter_note.setObjectName("hint")
        header.addWidget(self.filter_note)
        layout.addLayout(header)

        self.model = _Model(theme, self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setSortingEnabled(True)
        self.table.setStyleSheet(f"""
            QTableView {{
                background: {theme.card};
                alternate-background-color: {theme.bg_alt};
                border: 1px solid {theme.border};
                border-radius: 10px;
                selection-background-color: {theme.accent_dim};
                selection-color: {theme.text};
                outline: none;
            }}
            QHeaderView::section {{
                background: {theme.bg_alt};
                color: {theme.text_faint};
                border: none;
                border-bottom: 1px solid {theme.border};
                padding: 7px 8px;
                font-size: 11px;
            }}
        """)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.Interactive)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        for index, (_title, _key, width) in enumerate(COLUMNS):
            if index != 1:
                self.table.setColumnWidth(index, width)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.more = QPushButton(tr("Load more"))
        self.more.setObjectName("secondary")
        self.more.clicked.connect(self.more_requested)
        footer.addWidget(self.more)
        footer.addStretch(1)
        self.footnote = QLabel(tr("Click a heading to sort · double-click a row to reveal it"))
        self.footnote.setObjectName("hint")
        footer.addWidget(self.footnote)
        layout.addLayout(footer)

        self.setCentralWidget(central)

        self.table.sortByColumn(1, Qt.DescendingOrder)
        self.table.doubleClicked.connect(self._reveal)
        self._on_sort = lambda column, _order=Qt.AscendingOrder: self.sort_changed.emit(
            SORT_KEYS.get(column, "date_desc")
        )
        self.table.horizontalHeader().sortIndicatorChanged.connect(self._on_sort)
        QShortcut(QKeySequence.Close, self, self.close)

    def set_rows(self, rows, total: int, filter_note: str = "") -> None:
        self.model.set_rows(rows, total)
        self.headline.setText(tr("{count} photos", count=f"{total:,}"))
        self.filter_note.setText(filter_note)
        shown = len(self.model.rows)
        self.more.setVisible(shown < total)
        self.more.setText(tr("Load more ({count} left)", count=f"{total - shown:,}"))

    def selected_path(self) -> str | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        row = self.model.row_at(indexes[0].row())
        return row["rel_path"] if row else None

    def _reveal(self) -> None:
        path = self.selected_path()
        if path:
            self.revealed.emit(path)
