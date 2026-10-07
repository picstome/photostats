"""Scan status for the header.

The previous design hid progress behind a translucent overlay that was never
given any geometry, so a scan of tens of thousands of files ran with no visible
feedback at all. Progress now lives permanently in the header: there is always a
place where the app says what it is doing, whether idle, scanning or finished.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QWidget

from ...core.indexer import PHASE_PAUSED, PHASE_WALK, Progress
from ...i18n import tr

IDLE = "idle"


def format_duration(seconds: float) -> str:
    """'3s', '2m 05s', '1h 04m' — rounded the way a person would say it."""
    if seconds < 1:
        return f"{seconds:.0f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, rest = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {rest:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def format_count(value: int) -> str:
    return f"{value:,}"


class ScanStatus(QWidget):
    """One line that always reports what the app is doing."""

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.state = IDLE
        self.last_summary = ""
        #: The most recent update, so a dialog opened later can catch up.
        self.progress: Progress | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.dot = QLabel("●")
        self.dot.setFixedWidth(12)
        self.dot.setAlignment(Qt.AlignCenter)

        self.message = QLabel("")
        self.message.setStyleSheet(f"color: {theme.text_dim};")

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(220)
        self.bar.setFixedHeight(6)
        self.bar.setStyleSheet(f"""
            QProgressBar {{
                background: {theme.bar_bg};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{ background: {theme.accent}; border-radius: 3px; }}
        """)
        self.bar.setVisible(False)

        self.detail = QLabel("")
        self.detail.setObjectName("hint")

        layout.addWidget(self.dot)
        layout.addWidget(self.message)
        layout.addWidget(self.bar)
        layout.addWidget(self.detail)
        layout.addStretch(1)

    # -- states ------------------------------------------------------------
    def set_idle(self, summary: str = "") -> None:
        """Nothing to report, so the header stays one thin band.

        The finished summary used to sit here permanently, which meant the
        header carried a second line saying much of what the footer already
        said, all the time.
        """
        self.state = IDLE
        self._set_dot(self.theme.text_faint)
        self.message.setText(summary or "Choose a photo folder to begin")
        self.detail.setText("")
        self.bar.setVisible(False)
        self.setVisible(False)

    def set_scanning(self, progress: Progress) -> None:
        self.state = "scanning"
        self.progress = progress
        self.setVisible(True)
        self._set_dot(self.theme.accent)
        if progress.phase == PHASE_WALK:
            # The walk has no known total, so show what it has found so far.
            self.message.setText(tr("Looking for photos"))
            self.detail.setText(
                f"{format_count(progress.indexed)} found" +
                (f" · {progress.detail.split('/')[-1]}" if "/" in progress.detail else "")
            )
            self.bar.setRange(0, 0)
            self.bar.setVisible(True)
            return

        self.message.setText(tr("Reading photo details"))
        if progress.total:
            done, total = min(progress.indexed, progress.total), progress.total
            self.bar.setRange(0, total)
            self.bar.setValue(done)
            self.bar.setVisible(True)
            percent = 100 * done / total if total else 0
            parts = [f"{format_count(done)} of {format_count(total)}", f"{percent:.0f}%"]
        else:
            self.bar.setVisible(False)
            parts = [f"{format_count(progress.indexed)} photos"]
        if progress.new:
            parts.append(f"{format_count(progress.new)} new")
        if progress.updated:
            parts.append(f"{format_count(progress.updated)} changed")
        if progress.cached:
            parts.append(f"{format_count(progress.cached)} already known")
        if progress.errors:
            parts.append(f"{format_count(progress.errors)} unreadable")
        if progress.rate > 0.5:
            parts.append(f"{progress.rate:,.0f}/s")
        if progress.eta > 1:
            parts.append(f"~{format_duration(progress.eta)} left")
        self.detail.setText(" · ".join(parts))

    def set_paused(self, summary: str) -> None:
        self.state = PHASE_PAUSED
        self.setVisible(True)
        self._set_dot(self.theme.border)
        self.message.setText(tr("Scan paused"))
        self.detail.setText(summary)
        self.bar.setVisible(False)

    def set_finished(self, summary: str, detail: str = "") -> None:
        """Finished: hand the line to the caller and leave the header."""
        self.state = "done"
        self._set_dot(self.theme.accent)
        self.message.setText(summary)
        self.detail.setText(detail)
        self.bar.setVisible(False)
        self.last_summary = f"{summary} · {detail}" if detail else summary

    def text(self) -> str:
        """The line this widget would show, for the footer to reuse."""
        parts = [self.message.text()]
        if self.detail.text():
            parts.append(self.detail.text())
        return " · ".join(parts)

    def set_error(self, message: str) -> None:
        self.state = "error"
        self.setVisible(True)
        self._set_dot(self.theme.accent)
        self.message.setText(message)
        self.detail.setText("")
        self.bar.setVisible(False)

    def _set_dot(self, colour: str) -> None:
        self.dot.setStyleSheet(f"color: {colour};")


class StopButton(QPushButton):
    """The Scan/Stop control, kept separate so styling stays in one place."""

    def __init__(self, text: str, theme, parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("primary")
        self.theme = theme

    def set_scanning(self, scanning: bool) -> None:
        self.setText(tr("Stop" if scanning else "Scan"))
        self.setObjectName("danger" if scanning else "primary")
        self.style().unpolish(self)
        self.style().polish(self)
