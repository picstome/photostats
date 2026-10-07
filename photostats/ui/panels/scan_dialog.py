"""A dialog shown while a library is being scanned.

Progress used to be reported only in the header strip, which is easy to miss when
a large library takes minutes. This puts it in the middle of the screen — but it
is deliberately *not* modal and can be sent to the background, so a long scan
never blocks using the app. The header strip reports progress the whole time, so
whichever is on screen, the scan is never invisible.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ...core.indexer import PHASE_WALK, Progress
from ...i18n import tr
from .scan_status import format_count, format_duration


class ScanDialog(QDialog):
    """Progress, phase and the two things you might want to do about it."""

    cancel_requested = Signal()
    background_requested = Signal()

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setWindowTitle(tr("Scanning"))
        self.setModal(False)
        self.setMinimumWidth(460)
        self.setStyleSheet(f"QDialog {{ background: {theme.bg}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(10)

        self.phase_label = QLabel(tr("Looking for photos"))
        font = QFont(self.phase_label.font())
        font.setPointSizeF(font.pointSizeF() + 2)
        font.setWeight(QFont.DemiBold)
        self.phase_label.setFont(font)
        layout.addWidget(self.phase_label)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setStyleSheet(f"""
            QProgressBar {{
                background: {theme.bar_bg};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{ background: {theme.accent}; border-radius: 4px; }}
        """)
        layout.addWidget(self.bar)

        self.detail = QLabel("")
        self.detail.setStyleSheet(f"color: {theme.text_dim};")
        layout.addWidget(self.detail)

        self.file_label = QLabel("")
        self.file_label.setObjectName("hint")
        self.file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.file_label)

        layout.addSpacing(4)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.background = QPushButton(tr("Continue in background"))
        self.background.setObjectName("secondary")
        self.background.setToolTip(
            "Keep using the app while the scan finishes. Progress stays in the header."
        )
        self.background.clicked.connect(self._to_background)
        buttons.addWidget(self.background)
        buttons.addStretch(1)
        self.action = QPushButton(tr("Stop"))
        self.action.setObjectName("danger")
        self.action.clicked.connect(self._on_action)
        buttons.addWidget(self.action)
        layout.addLayout(buttons)

    # -- lifecycle ---------------------------------------------------------
    def begin(self) -> None:
        self.phase_label.setText(tr("Looking for photos"))
        self.bar.setRange(0, 0)
        self.detail.setText(tr("Walking the folder tree"))
        self.file_label.setText("")
        self.background.setEnabled(True)
        self.action.setText(tr("Stop"))
        self.show()
        self.raise_()

    def _to_background(self) -> None:
        self.background_requested.emit()
        self.hide()

    def _on_action(self) -> None:
        if self.action.text() == "Continue":
            self.hide()
            self.background_requested.emit()
            return
        self.action.setEnabled(False)
        self.action.setText(tr("Stopping…"))
        self.phase_label.setText(tr("Stopping"))
        self.cancel_requested.emit()

    # -- progress ----------------------------------------------------------
    def update_progress(self, progress: Progress) -> None:
        if progress.phase == PHASE_WALK:
            self.phase_label.setText(tr("Looking for photos"))
            self.bar.setRange(0, 0)
            found = format_count(progress.indexed)
            self.detail.setText(
                f"{found} photos found so far" + (f" · {progress.detail}" if progress.detail else "")
            )
            return

        self.phase_label.setText(tr("Reading photo details"))
        done = min(progress.indexed, progress.total) if progress.total else progress.indexed
        if progress.total:
            self.bar.setRange(0, progress.total)
            self.bar.setValue(done)
            percent = 100 * done / progress.total
            self.detail.setText(
                f"{format_count(done)} of {format_count(progress.total)} photos · {percent:.0f}%"
            )
        else:
            self.bar.setRange(0, 0)
            self.detail.setText(tr("{count} photos", count=format_count(progress.indexed)))

        bits = []
        if progress.new:
            bits.append(f"{format_count(progress.new)} new")
        if progress.updated:
            bits.append(f"{format_count(progress.updated)} changed")
        if progress.cached:
            bits.append(f"{format_count(progress.cached)} already known")
        if progress.errors:
            bits.append(f"{format_count(progress.errors)} unreadable")
        if progress.rate > 0.5:
            bits.append(f"{progress.rate:,.0f}/s")
        if progress.eta > 1:
            bits.append(f"about {format_duration(progress.eta)} left")
        if bits:
            self.detail.setText(self.detail.text() + "\n" + " · ".join(bits))
        if progress.detail:
            self.file_label.setText(progress.detail)

    def show_paused(self, message: str) -> None:
        self.phase_label.setText(tr("Scan paused"))
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.detail.setText(message)
        self.file_label.setText("")
        self.action.setText(tr("Continue"))
        self.action.setEnabled(True)
        self.background.setEnabled(False)
        self.show()
        self.raise_()

    def show_finished(self, summary: str, exiftool: str = "") -> None:
        self.phase_label.setText(tr("Done"))
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.detail.setText(summary)
        self.file_label.setText(
            tr("Metadata read with exiftool {version}", version=exiftool)
            if exiftool else ""
        )
        self.action.setText(tr("Close"))
        self.action.setEnabled(True)
        self.background.setEnabled(False)
        self.show()
        self.raise_()

    def closeEvent(self, event) -> None:  # noqa: D102, N802
        # Closing the dialog means "carry on quietly", never "stop the scan".
        if self.action.text() != "Close":
            self.background_requested.emit()
        super().closeEvent(event)
