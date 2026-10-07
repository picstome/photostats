"""Checkbox list of the values observed in a facet, with counts and search.

Shows how many photos each value has, so the list doubles as a legend for its
chart and the user can pick a filter without leaving the sidebar.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr

ROW_HEIGHT = 28
INDICATOR_SIZE = 14

#: Qt hands CheckStateRole back as a plain int, and in PySide6 6.11 a plain int
#: does not compare equal to the enum: ``data(Qt.CheckStateRole) == Qt.Checked``
#: is False even when the box is ticked. Compare against the numeric value.
CHECKED = Qt.Checked.value


class _Delegate(QStyledItemDelegate):
    """Draws label + count + a share bar, so counts stay readable in dark mode."""

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect.adjusted(6, 1, -6, -1)
        highlighted = bool(option.state & QStyle.State_MouseOver) or bool(
            option.state & QStyle.State_Selected
        )
        checked = index.data(Qt.CheckStateRole) == CHECKED
        # Paint the row ourselves rather than inheriting the item background,
        # which otherwise follows the palette and can be unreadable.
        painter.setPen(Qt.NoPen)
        painter.setBrush(
            QColor(self.theme.card_hover if highlighted else self.theme.card)
        )
        painter.drawRoundedRect(rect, 6, 6)
        if checked:
            painter.setBrush(QColor(self.theme.accent_dim))
            painter.drawRoundedRect(rect.adjusted(0, 0, -3, 0), 6, 6)

        self._paint_tick(painter, rect, checked)

        metrics = option.fontMetrics
        count = index.data(Qt.UserRole + 1) or 0
        share = index.data(Qt.UserRole + 2) or 0.0

        # Right side, left to right: share bar, then count. Reserve exactly what
        # they need, measured from the font, so the label can never collide
        # with either — a fixed gap is wrong for every label length.
        right_pad = 8
        count_text = f"{count:,}"
        count_w = metrics.horizontalAdvance(count_text) + 4
        bar_w = 30 if share > 0 else 0
        gap = 6
        count_rect = QRectF(
            rect.right() - right_pad - count_w,
            rect.y(),
            count_w,
            rect.height(),
        )
        bar_rect = QRectF(
            count_rect.left() - (gap + bar_w),
            rect.y(),
            bar_w,
            rect.height(),
        )

        text_rect = QRectF(
            rect.left() + 22,
            rect.y(),
            max(24.0, bar_rect.left() - gap - (rect.left() + 22)),
            rect.height(),
        )
        label = metrics.elidedText(
            str(index.data(Qt.DisplayRole)), Qt.ElideRight, int(text_rect.width())
        )
        painter.setPen(QColor(self.theme.text if checked else self.theme.text_dim))
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, label)

        painter.setPen(QColor(self.theme.text_faint))
        painter.drawText(count_rect, Qt.AlignVCenter | Qt.AlignRight, count_text)

        if bar_w:
            bar_height = 4
            bar_y = rect.center().y() - bar_height // 2
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self.theme.bar_bg))
            painter.drawRoundedRect(QRectF(bar_rect.x(), bar_y, bar_w, bar_height), 2, 2)
            painter.setBrush(QColor(self.theme.accent_dim))
            painter.drawRoundedRect(
                QRectF(bar_rect.x(), bar_y, max(2.0, bar_w * share), bar_height), 2, 2
            )
        painter.restore()

    def _paint_tick(self, painter: QPainter, rect, checked: bool) -> None:
        """Draw the box and the tick ourselves.

        Asking the style to draw PE_IndicatorCheckBox looks like the obvious
        thing to do and it quietly fails: with the Fusion style plus a
        stylesheet on the list, the result is byte-identical checked or not, so
        a selection filtered everything except the mark that said so. Owning
        the two shapes also means the tick uses the theme accent and looks the
        same on every platform.
        """
        box = QRectF(
            4.0,
            rect.y() + (rect.height() - INDICATOR_SIZE) / 2,
            INDICATOR_SIZE,
            INDICATOR_SIZE,
        )
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if checked:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self.theme.accent))
            painter.drawRoundedRect(box, 4, 4)
            # The tick, as two strokes, so it survives any scale factor.
            tick = QPainterPath(QPointF(box.left() + box.width() * 0.26,
                                        box.center().y()))
            tick.lineTo(QPointF(box.left() + box.width() * 0.44,
                                box.bottom() - box.height() * 0.26))
            tick.lineTo(QPointF(box.right() - box.width() * 0.22,
                                box.top() + box.height() * 0.27))
            pen = QPen(QColor(self.theme.accent_text), 2.0)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(tick)
        else:
            pen = QPen(QColor(self.theme.text_faint), 1.4)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(box, 4, 4)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt naming
        size = super().sizeHint(option, index)
        return QSize(size.width(), ROW_HEIGHT)


class CheckList(QWidget):
    """Searchable, tri-state list of facet values."""

    selection_changed = Signal(list)

    def __init__(self, theme, placeholder: str = "Filter…", parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self._values: list[tuple[str, int, float]] = []
        self._selected: set[str] = set()
        self._needle = ""
        self._search_pending = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._flush_search)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setItemDelegate(_Delegate(theme, self.list))
        self.list.setSelectionMode(QAbstractItemView.NoSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setUniformItemSizes(True)
        # A list of 40 bodies would otherwise push every other control off
        # screen; scrolling inside the list keeps the panel predictable.
        self.list.setMaximumHeight(6 * ROW_HEIGHT + 4)
        self.list.itemChanged.connect(self._on_item_changed)
        self.list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(4)
        self.select_all = QPushButton(tr("All"))
        self.select_none = QPushButton(tr("None"))
        self.select_all.setObjectName("linkButton")
        self.select_none.setObjectName("linkButton")
        self.select_all.clicked.connect(lambda: self._set_all(True))
        self.select_none.clicked.connect(lambda: self._set_all(False))
        buttons.addWidget(self.select_all)
        buttons.addWidget(self.select_none)
        self.count_label = QLabel("")
        self.count_label.setObjectName("hint")
        buttons.addStretch(1)
        buttons.addWidget(self.count_label)
        layout.addLayout(buttons)

        # The viewport is a separate widget that ignores the stylesheet's
        # background, and Qt fills the empty space below the last row with the
        # palette's Base colour (white). Set that palette explicitly.
        palette = self.list.palette()
        palette.setColor(QPalette.Base, QColor(theme.bg_alt))
        palette.setColor(QPalette.Window, QColor(theme.bg_alt))
        palette.setColor(QPalette.Highlight, QColor(theme.card_hover))
        palette.setColor(QPalette.HighlightedText, QColor(theme.text))
        self.list.setPalette(palette)
        self.list.setAutoFillBackground(True)
        self.list.viewport().setAutoFillBackground(True)

        # Every ::item property must be stated: styling it partially makes Qt
        # fill the rest from the default palette.
        self.list.setStyleSheet(f"""
            QListWidget {{
                background: {theme.bg_alt};
                border: none;
                padding: 0;
            }}
            QListWidget::item {{
                background: transparent;
                border: none;
                border-radius: 6px;
                margin: 0;
                padding: 0;
            }}
            QListWidget::item:selected {{ background: transparent; }}
        """)

    # -- data --------------------------------------------------------------
    def set_values(self, values: list[tuple[str, int, float]], selected: set[str] | None = None) -> None:
        """New data always means a full rebuild, even if the needle is unchanged."""
        self._values = list(values)
        self._selected = set(selected or ())
        self._needle = None  # force _apply_search past its "unchanged" short-circuit
        self._apply_search(self.search.text())

    def set_selected(self, selected: set[str]) -> None:
        self._selected = set(selected)
        for index in range(self.list.count()):
            item = self.list.item(index)
            label = item.data(Qt.UserRole)
            wanted = Qt.Checked if label in self._selected else Qt.Unchecked
            if item.checkState() != wanted:
                self.list.blockSignals(True)
                item.setCheckState(wanted)
                self.list.blockSignals(False)
        self._update_toggles()

    def selected_values(self) -> list[str]:
        return [label for label, _count, _share in self._values if label in self._selected]

    def clear_selection(self) -> None:
        self.set_selected(set())

    # -- internals ---------------------------------------------------------
    def _apply_search(self, needle: str) -> None:
        needle = needle.strip().lower()
        if needle == self._needle:
            return
        self._needle = needle
        self.list.blockSignals(True)
        self.list.clear()
        visible = 0
        for label, count, share in self._values:
            if needle and needle not in label.lower():
                continue
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if label in self._selected else Qt.Unchecked)
            item.setData(Qt.UserRole, label)
            item.setData(Qt.UserRole + 1, count)
            item.setData(Qt.UserRole + 2, share)
            self.list.addItem(item)
            visible += 1
        self.list.blockSignals(False)
        self.count_label.setText(
            tr("{visible} of {total}", visible=visible, total=len(self._values))
            if needle else ""
        )
        self._update_toggles()
        self._search_pending = False
        self._flush_search()

    def _flush_search(self) -> None:
        """Re-run the filter shortly after typing stops, not on every keystroke."""
        if self._search_pending:
            return
        self._search_pending = True
        QTimer.singleShot(120, self._apply_search_now)

    def _apply_search_now(self) -> None:
        self._search_pending = False
        self._apply_search(self.search.text())

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        """Toggle the clicked row: the whole row is a target, not just the box."""
        wanted = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
        if item.checkState() != wanted:
            item.setCheckState(wanted)   # itemChanged emits selection_changed

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        label = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            self._selected.add(label)
        else:
            self._selected.discard(label)
        self._update_toggles()
        self.selection_changed.emit(sorted(self._selected))

    def _set_all(self, checked: bool) -> None:
        self.set_selected({label for label, _c, _s in self._values} if checked else set())
        self.selection_changed.emit(sorted(self._selected))

    def _update_toggles(self) -> None:
        self.select_all.setEnabled(bool(self._selected) and len(self._selected) < len(self._values))
        self.select_none.setEnabled(bool(self._selected))
