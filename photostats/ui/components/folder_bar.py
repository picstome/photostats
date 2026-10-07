"""Top bar: which library is open, where the cache lives, and global actions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from .icons import gear, moon, sun

RECENT_PLACEHOLDER = "Choose a photo folder…"


class _ElidedLabel(QLabel):
    """A label that shortens its own text to fit instead of being clipped.

    A QLabel with a long path either forces the whole layout wider than the
    window or truncates the string mid-glyph. This keeps the full text for
    tooltips and for copying, but paints "…/parent/folder" when space is tight.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self._full = text or ""
        super().setText(self._elide(self._full, self.width()))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        elided = self._elide(self._full, self.width())
        if elided != self.text():
            super().setText(elided)

    def full_text(self) -> str:
        return self._full

    def _elide(self, text: str, width: int) -> str:
        metrics = self.fontMetrics()
        if width <= 0 or metrics.horizontalAdvance(text) <= width:
            return text
        # Keep the tail: the last folders identify the library.
        parts = text.replace("\\", "/").split("/")
        while len(parts) > 1 and metrics.horizontalAdvance("…/" + "/".join(parts)) > width:
            parts.pop(0)
        return "…/" + "/".join(parts)


class FolderBar(QWidget):
    """Folder picker with a recent-folders menu and the scan controls."""

    folder_chosen = Signal(str)
    rescan_requested = Signal()
    scan_cancelled = Signal()
    settings_requested = Signal()
    theme_toggled = Signal()
    library_cleared = Signal()

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.scanning = False
        self._has_folder = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 5, 16, 6)
        layout.setSpacing(8)

        # Left: what this page is about. An eyebrow saying what the app is, the
        # library's name as the actual title, and the path underneath to check
        # it against. A bare folder name read as a label with nothing above it.
        identity = QVBoxLayout()
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(1)
        self.eyebrow = QLabel(tr("Your photo stats"))
        self.eyebrow.setObjectName("libraryEyebrow")
        self.name = QLabel(RECENT_PLACEHOLDER)
        self.name.setObjectName("libraryName")
        # The identity labels are the only elastic thing in the bar. Without a
        # zero minimum their width was the width of the whole string, so a long
        # path pushed the layout past the bar and the theme button hung off the
        # right edge — visible in Spanish, where "Analizar" is wider than "Scan".
        for label in (self.eyebrow, self.name):
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            label.setMinimumWidth(0)
        # The path also elides in the middle rather than being cut mid-glyph.
        self.path = _ElidedLabel()
        self.path.setObjectName("libraryPath")
        identity.addWidget(self.eyebrow)
        identity.addWidget(self.name)
        identity.addWidget(self.path)
        # The identity gets the stretch, not a separate spacer: with Ignored
        # labels the layout otherwise hands them zero width and the folder name
        # disappears entirely.
        layout.addLayout(identity, 1)

        # Right: the actions, in the order they are reached for. Browse and the
        # recent list are the same intent, so they are one button.
        # A QPushButton with the menu popped by hand, rather than a QToolButton:
        # a ToolButton reserves arrow space even with the arrow hidden, which
        # squeezed "Open" into a clipped 49px box.
        self.browse = QPushButton(tr("Open"))
        self.browse.setObjectName("secondary")
        self.browse.setCursor(Qt.PointingHandCursor)
        self.browse.setToolTip(tr("Open a photo folder"))
        self.browse.clicked.connect(self._toggle_open_menu)
        layout.addWidget(self.browse)

        self.scan = QPushButton(tr("Scan"))
        self.scan.setObjectName("primary")
        self.scan.setMinimumWidth(104)
        self.scan.clicked.connect(self._on_scan_clicked)
        layout.addWidget(self.scan)

        self.settings = QToolButton()
        self.settings.setObjectName("iconButton")
        self.settings.setCursor(Qt.PointingHandCursor)
        self.settings.setToolTip(tr("Settings"))
        self.settings.clicked.connect(self.settings_requested)
        layout.addWidget(self.settings)

        self.theme_button = QToolButton()
        self.theme_button.setObjectName("iconButton")
        self.theme_button.setCursor(Qt.PointingHandCursor)
        self.theme_button.clicked.connect(self.theme_toggled)
        layout.addWidget(self.theme_button)

        self._set_icons()
        self._build_menu()

    # -- state -------------------------------------------------------------
    def _build_menu(self) -> None:
        self.recent_menu = QMenu(self)
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)

    def _toggle_open_menu(self) -> None:
        position = self.browse.mapToGlobal(
            QPoint(0, self.browse.height() + 4))
        self.recent_menu.popup(position)

    def _fill_recent_menu(self) -> None:
        menu = self.recent_menu
        menu.clear()
        recents = getattr(self, "recents", [])
        if not recents:
            empty = menu.addAction(tr("No recent folders"))
            empty.setEnabled(False)
            return
        heading = menu.addAction(tr("Recent"))
        heading.setEnabled(False)
        heading.setObjectName("menuHeading")
        menu.addSeparator()
        for folder in recents:
            action = menu.addAction(_shorten(str(folder), 56))
            action.setToolTip(str(folder))
            action.triggered.connect(
                lambda _checked=False, target=folder: self.folder_chosen.emit(target)
            )
        if recents:
            menu.addSeparator()
            clear = menu.addAction(tr("Clear list"))
            clear.triggered.connect(lambda: setattr(self, "recents", []))
        menu.addSeparator()
        pick = menu.addAction(tr("Browse…"))
        pick.triggered.connect(self._emit_browse)

    def set_recents(self, recents: list[str]) -> None:
        self.recents = recents

    def set_folder(self, folder: Path | str | None) -> None:
        """Show the library's name prominently and its path underneath."""
        if folder is None:
            self._has_folder = False
            self.name.setText(tr("No folder chosen"))
            self.path.setText(tr("Choose a folder of photos to begin"))
            self.path.setToolTip("")
            return
        text = str(folder)
        name = Path(text).name or text
        self._has_folder = True
        self.name.setText(name)
        parent = str(Path(text).parent)
        self.path.setText(parent if parent != text else text)
        self.name.setToolTip(text)
        self.path.setToolTip(text)

    def set_scanning(self, scanning: bool) -> None:
        self.scanning = scanning
        self.scan.setText(tr("Stop") if scanning else tr("Scan"))
        self.scan.setObjectName("danger" if scanning else "primary")
        self.browse.setEnabled(not scanning)

    def _set_icons(self) -> None:
        """Draw the icons in the theme's own colours."""
        colour = self.theme.text_dim
        self.settings.setIcon(gear(colour))
        self.settings.setIconSize(QSize(18, 18))
        self.theme_button.setIcon(moon(colour) if self.theme.is_dark else sun(colour))
        self.theme_button.setIconSize(QSize(18, 18))
        # The Open button is a plain push button now, so it gets no dropdown
        # arrow; the fact that it opens a menu is a small cost for a button that
        # is no longer clipped.

    def set_theme(self, theme) -> None:
        """Repaint after a theme change; icons bake their colours in."""
        self.theme = theme
        self._set_icons()

    @property
    def has_folder(self) -> bool:
        return self._has_folder

    # -- events ------------------------------------------------------------
    def _emit_browse(self) -> None:
        self.folder_chosen.emit("__browse__")

    def _on_scan_clicked(self) -> None:
        if self.scanning:
            self.scan_cancelled.emit()
        else:
            self.rescan_requested.emit()


def _shorten(path: str, keep: int = 46) -> str:
    """Middle-elide a long path so the folder name stays readable."""
    if len(path) <= keep:
        return path
    head, tail = path[: keep // 2 - 2], path[-(keep // 2 - 1):]
    return f"{head}…{tail}"


class DropHint(QLabel):
    """Shown when the window has no library yet."""

    def __init__(self, theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setText(tr("Drop a photo folder here"))
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setStyleSheet(
            f"border: 2px dashed {theme.border}; border-radius: 12px;"
            f"color: {theme.text_dim}; font-size: 14px;"
        )

    def set_active(self, active: bool) -> None:
        colour = self.theme.accent if active else self.theme.border
        self.setStyleSheet(
            f"border: 2px dashed {colour}; border-radius: 12px;"
            f"color: {self.theme.text if active else self.theme.text_dim}; font-size: 14px;"
        )


class SortSelector(QComboBox):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.addItem("Newest first", "date_desc")
        self.addItem("Oldest first", "date_asc")
        self.addItem("Camera", "camera")
        self.addItem("Lens", "lens")
        self.addItem("ISO (high to low)", "iso_desc")
        self.addItem("ISO (low to high)", "iso_asc")
        self.addItem("Shutter speed", "shutter")
        self.addItem("Aperture", "aperture")
        self.addItem("Focal length", "focal")
        self.addItem("File name", "name")
        self.setObjectName("secondary")
