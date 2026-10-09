"""Small top-of-page components: summary tiles, insights line, welcome screen."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr


class Tile(QFrame):
    """One figure with a caption. The first thing you read on the page."""

    def __init__(self, theme, caption: str, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setObjectName("tile")
        self.setStyleSheet(f"""
            QFrame#tile {{
                background: {theme.card};
                border: 1px solid {theme.border};
                border-radius: 10px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        self.value = QLabel("—")
        font = QFont(self.value.font())
        font.setPointSizeF(font.pointSizeF() + 4)
        font.setWeight(QFont.DemiBold)
        self.value.setFont(font)
        self.caption = QLabel(caption)
        self.caption.setObjectName("tileCaption")
        # One line, always. A caption that wrapped to two lines made its tile
        # taller than its neighbours and the row lost its shared baseline.
        self.caption.setWordWrap(False)
        self.caption.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        layout.addWidget(self.value)
        layout.addWidget(self.caption)
        self.setMinimumHeight(self.sizeHint().height())

    def set(self, text: str) -> None:
        self.value.setText(text)


class SummaryTiles(QWidget):
    """Four figures that frame everything below them."""

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.matched = Tile(theme, "photos shown")
        self.total = Tile(theme, "in this library")
        self.sources = Tile(theme, "cameras used")
        self.span = Tile(theme, "date range")
        for tile in (self.matched, self.total, self.sources, self.span):
            tile.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            layout.addWidget(tile)
        self._level()

    def _level(self) -> None:
        """Every tile the same height, whatever their captions say."""
        tallest = max(tile.sizeHint().height() for tile in self._tiles())
        for tile in self._tiles():
            tile.setMinimumHeight(tallest)
            tile.setMaximumHeight(tallest)

    def _tiles(self):
        return (self.matched, self.total, self.sources, self.span)

    def update_summary(self, matched: int, total: int, cameras: int, span: str) -> None:
        self.matched.set(f"{matched:,}")
        self.total.set(f"{total:,}")
        self.sources.set(f"{cameras:,}")
        self.span.set(span)
        share = (matched / total * 100) if total else 0.0
        self.matched.caption.setText(
            tr("{count} photos shown", count=f"{matched:,}") if matched == total
            else tr("photos shown ({share}%)", share=f"{share:.0f}")
        )
        self._level()


class InsightsBar(QWidget):
    """A row of short facts about the current selection.

    Built from separate labels rather than one rich-text label: inline colours in
    rich text render inconsistently across platforms, and pills are easier to
    scan than a sentence.
    """

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

    def clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def set_insights(self, items) -> None:
        self.clear()
        if not items:
            note = QLabel(tr("Nothing here yet — open a photo folder to begin"))
            note.setObjectName("hint")
            self._layout.addWidget(note)
            self._layout.addStretch(1)
            return
        for insight in items[:3]:
            self._layout.addWidget(self._pill(insight))
        self._layout.addStretch(1)

    def _pill(self, insight) -> QWidget:
        head, tail = _split_emphasis(insight)
        pill = QWidget()
        layout = QHBoxLayout(pill)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        if head:
            badge = QLabel(head)
            badge.setStyleSheet(f"""
                QLabel {{
                    background: {self.theme.accent};
                    color: {self.theme.accent_text};
                    border-radius: 9px;
                    padding: 2px 8px;
                    font-size: 12px;
                    font-weight: 600;
                }}
            """)
            layout.addWidget(badge)

        body = QLabel(tail)
        body.setStyleSheet(f"color: {self.theme.text_dim}; font-size: 12px;")
        layout.addWidget(body)
        return pill

    def set_message(self, text: str) -> None:
        self.clear()
        note = QLabel(text)
        note.setStyleSheet(f"color: {self.theme.text_faint};")
        self._layout.addWidget(note)
        self._layout.addStretch(1)


def _split_emphasis(insight) -> tuple[str, str]:
    """'60% of these are from X' + emphasis '60%' -> ('60%', 'of these are from X')."""
    text, emphasis = insight.text, insight.emphasis
    if emphasis and text.startswith(emphasis):
        return emphasis, text[len(emphasis):].lstrip(" ·,")
    return emphasis or "", text


class WelcomeScreen(QWidget):
    """Shown until a folder is opened: one obvious thing to do."""

    def __init__(self, theme, on_browse, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(12)

        title = QLabel(tr("Photo Stats"))
        title.setAlignment(Qt.AlignCenter)
        font = QFont(title.font())
        font.setPointSizeF(font.pointSizeF() + 10)
        font.setWeight(QFont.DemiBold)
        title.setFont(font)
        layout.addWidget(title)

        subtitle = QLabel(tr("Choose a folder of photos to see what you shoot"))
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(f"color: {theme.text_dim}; font-size: 14px;")
        layout.addWidget(subtitle)

        button = QPushButton(tr("Choose photo folder…"))
        button.setObjectName("primary")
        button.setFixedWidth(230)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(on_browse)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)

        hint = QLabel(tr("…or drag a folder onto this window"))
        hint.setAlignment(Qt.AlignCenter)
        hint.setObjectName("hint")
        layout.addWidget(hint)

        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # noqa: D102, N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: D102, N802
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_dir():
                self.window().open_library(path)
                break
