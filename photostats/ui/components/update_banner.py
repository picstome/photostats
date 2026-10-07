"""A one-line banner offering a newer release."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

from ...i18n import tr


class UpdateBanner(QWidget):
    """Shown only when GitHub has a newer release than this build.

    Hidden by default and never on the welcome screen: an update prompt is not
    the first thing someone opening the app should see. The download goes to
    this platform's file when the release carries one, and to the release page
    otherwise.
    """

    #: Emitted with the URL when no browser would take it, so the window can
    #: say so rather than appearing to do nothing.
    open_failed = Signal(str)

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self._url = ""
        self.setObjectName("updateBanner")
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 8, 8)
        layout.setSpacing(10)

        self.label = QLabel("")
        layout.addWidget(self.label, 1)

        self.download = QPushButton(tr("Download"))
        self.download.setObjectName("primary")
        self.download.setCursor(Qt.PointingHandCursor)
        self.download.clicked.connect(self._open)
        layout.addWidget(self.download)

        self.close = QToolButton()
        self.close.setText("\u00d7")
        self.close.setObjectName("iconButton")
        self.close.setCursor(Qt.PointingHandCursor)
        self.close.setToolTip(tr("Dismiss"))
        self.close.clicked.connect(self._dismiss)
        layout.addWidget(self.close)

        self._restyle()

    def show_release(self, release) -> None:
        self.label.setText(
            tr("Photo Stats {version} is available", version=release.version))
        # This platform's file if the release has it, the release page if not.
        self._url = release.asset_for() or release.url
        self.download.setEnabled(bool(self._url))
        self.setVisible(True)

    def _open(self) -> None:
        if self._url and not QDesktopServices.openUrl(QUrl(self._url)):
            self.open_failed.emit(self._url)

    def _dismiss(self) -> None:
        self.setVisible(False)

    def _restyle(self) -> None:
        self.setStyleSheet(f"""
            QWidget#updateBanner {{
                background: {self.theme.bg_alt};
                border: 1px solid {self.theme.accent};
                border-radius: 10px;
            }}
            QWidget#updateBanner QLabel {{
                color: {self.theme.text};
                font-weight: 600;
            }}
        """)
