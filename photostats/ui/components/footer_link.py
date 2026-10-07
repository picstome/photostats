"""A link in the footer that opens a web page in the normal browser."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel

from ...i18n import tr


class FooterLink(QLabel):
    """The Picstome.com attribution in the status bar.

    Opens on click rather than on hover, because following a link you did not
    mean to follow is worse than not having one. A plain QLabel with a URL would
    look clickable and do nothing, so the pointer, the underline and the click
    handler all have to be here.
    """

    #: Emitted with the URL when the browser could not be opened, so the caller
    #: can say so instead of appearing to do nothing.
    open_failed = Signal(str)

    def __init__(self, text: str, url: str, theme, parent=None) -> None:
        super().__init__(text, parent)
        self.theme = theme
        self.url = url
        self._hovered = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setToolTip(url)
        self._restyle()

    def mousePressEvent(self, event) -> None:  # noqa: D102, N802
        """Open on click anywhere in the label.

        QLabel's linkActivated signal is only emitted for an HTML anchor, so a
        label showing the bare domain would swallow the click and do nothing.
        """
        if event.button() == Qt.LeftButton:
            self._open()
        super().mousePressEvent(event)

    def _open(self) -> None:
        if not QDesktopServices.openUrl(QUrl(self.url)):
            self.open_failed.emit(self.url)

    # -- appearance --------------------------------------------------------
    def _restyle(self) -> None:
        colour = self.theme.accent_dim if self._hovered else self.theme.text_faint
        self.setStyleSheet(f"""
            QLabel {{
                color: {colour};
                {'text-decoration: underline;' if self._hovered else ''}
            }}
        """)

    def enterEvent(self, event) -> None:  # noqa: D102, N802
        self._hovered = True
        self._restyle()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: D102, N802
        self._hovered = False
        self._restyle()
        super().leaveEvent(event)

    def set_theme(self, theme) -> None:
        """Repaint after a theme change; widgets bake their colours in."""
        self.theme = theme
        self._restyle()

    @staticmethod
    def failure_message(url: str) -> str:
        return tr("Could not open {url} in your browser", url=url)
