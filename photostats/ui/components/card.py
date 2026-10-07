"""Cards, chips and collapsible sections."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class Card(QFrame):
    """Rounded surface with a hairline border; the base of every panel."""

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setObjectName("card")
        self.setStyleSheet(f"""
            QFrame#card {{
                background: {theme.card};
                border: 1px solid {theme.border};
                border-radius: 10px;
            }}
        """)


class Section(QWidget):
    """A titled block that collapses.

    Starts collapsed: a sidebar of eight open panels buries the two or three a
    photographer actually reaches for.
    """

    toggled_open = Signal(bool)

    def __init__(self, theme, title: str, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.header = QToolButton()
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setChecked(False)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.DownArrow)
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setObjectName("sectionHeader")
        self.header.toggled.connect(self._on_toggle)
        layout.addWidget(self.header)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 4)
        self.body_layout.setSpacing(6)
        layout.addWidget(self.body)
        self.body.setVisible(False)
        self.header.setArrowType(Qt.RightArrow)

    def _on_toggle(self, checked: bool) -> None:
        self.header.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.body.setVisible(checked)
        self.toggled_open.emit(checked)

    def set_expanded(self, expanded: bool) -> None:
        """Open or close without pretending the user clicked it.

        Used to open the section a photographer reaches for first; the signal is
        emitted so anyone wiring to :attr:`toggled_open` stays in step, but the
        arrow is set here rather than by a real toggle event.
        """
        self.header.setChecked(expanded)
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.body.setVisible(expanded)

    def set_header_text(self, text: str) -> None:
        self.header.setText(text)


class Chip(QLabel):
    """A removable filter pill shown above the charts."""

    removed = Signal()

    def __init__(self, theme, label: str, value: str = "", tone: str = "accent", parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        colours = {
            "accent": (theme.accent, theme.accent_text),
            "neutral": (theme.card_hover, theme.text),
        }
        background, foreground = colours.get(tone, colours["neutral"])
        self.setText(f"{label}{f'  {value}' if value else ''}   ✕")
        self.setStyleSheet(f"""
            QLabel {{
                background: {background};
                color: {foreground};
                border-radius: 11px;
                padding: 3px 9px;
                font-size: 12px;
            }}
        """)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def mousePressEvent(self, event) -> None:  # noqa: D102, N802
        if event.button() == Qt.LeftButton:
            self.removed.emit()
        super().mousePressEvent(event)


class StatTile(QFrame):
    """A single number with a caption."""

    def __init__(self, theme, caption: str, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(0)
        self.value = QLabel("—")
        font = QFont(self.value.font())
        font.setPointSizeF(font.pointSizeF() + 5)
        font.setWeight(QFont.DemiBold)
        self.value.setFont(font)
        self.caption = QLabel(caption)
        self.caption.setStyleSheet(f"color: {theme.text_faint}; font-size: 11px;")
        layout.addWidget(self.value)
        layout.addWidget(self.caption)

    def set_value(self, text: str) -> None:
        self.value.setText(text)


class Divider(QFrame):
    """One-pixel rule."""

    def __init__(self, theme, horizontal: bool = True, parent=None) -> None:
        super().__init__(parent)
        if horizontal:
            self.setFixedHeight(1)
        else:
            self.setFixedWidth(1)
        self.setStyleSheet(f"background: {theme.border};")


class EmptyState(QWidget):
    """Friendly placeholder shown when there is nothing to display."""

    def __init__(self, theme, title: str, detail: str = "", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)
        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet(f"font-size: 16px; color: {theme.text_dim};")
        self.detail_label = QLabel(detail)
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet(f"color: {theme.text_faint};")
        layout.addWidget(self.title_label)
        layout.addWidget(self.detail_label)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_text(self, title: str, detail: str = "") -> None:
        self.title_label.setText(title)
        self.detail_label.setText(detail)


class Row(QWidget):
    """Label on the left, control on the right."""

    def __init__(self, label: str, widget: QWidget, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        caption = QLabel(label)
        caption.setObjectName("hint")
        layout.addWidget(caption)
        layout.addStretch(1)
        layout.addWidget(widget)
