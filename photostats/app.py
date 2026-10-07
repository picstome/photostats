"""Application bootstrap: QApplication, logging, excepthook, single-instance."""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from . import APP_NAME, ORG_NAME, __version__
from .core.config import AppConfig
from .core.paths import Paths
from .i18n import product_title, set_language
from .ui import theme
from .ui.assets import LOGO_MARK, install_fonts, logo
from .ui.theme import FLORAL_WHITE, PINE_BLUE


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="photostats", description=f"{APP_NAME} — photo metadata analyzer")
    parser.add_argument("folder", nargs="?", help="photo library to open")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument(
        "--audit-translations",
        action="store_true",
        help="list untranslated strings for every bundled language and exit",
    )
    return parser.parse_args(argv)


def setup_logging(paths: Paths) -> logging.Logger:
    logger = logging.getLogger("photostats")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    try:
        handler = RotatingFileHandler(paths.log_file, maxBytes=1_000_000, backupCount=3,
                                      encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


def app_icon(color: str = PINE_BLUE) -> QIcon:
    """The window icon: the Picstome mark when supplied, a drawn one otherwise.

    The real mark lives in ``photostats/assets/logos``; when it is not there the
    fallback is drawn in the brand's pine blue rather than a generic accent, so
    an install without the assets still looks like part of the family.
    """
    supplied = logo(LOGO_MARK)
    if supplied is not None:
        return QIcon(str(supplied))

    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(8, 8, size - 16, size - 16, 56, 56)
    # An aperture: concentric blades, which is the shape the real mark is built
    # from. Drawn rather than traced so nothing here is a guess at the artwork.
    painter.setBrush(QColor(FLORAL_WHITE))
    painter.drawEllipse(QRect(74, 74, 108, 108))
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRect(94, 94, 68, 68))
    painter.setBrush(QColor(FLORAL_WHITE))
    for index in range(6):
        angle = index * 60
        painter.save()
        painter.translate(size / 2, size / 2)
        painter.rotate(angle)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(6, -7, size / 2 - 34, 14, 7, 7)
        painter.restore()
    painter.setBrush(QColor(FLORAL_WHITE))
    painter.drawEllipse(QRect(106, 106, 44, 44))
    painter.end()
    return QIcon(pixmap)


def install_excepthook(logger: logging.Logger) -> None:
    # One dialog per distinct failure, not one per occurrence. An exception in
    # a mouse-move handler fires on every pixel of movement, and a modal dialog
    # for each one makes the app look broken in a way that hides the real
    # problem: the buttons simply stop responding.
    reported: set[tuple] = set()

    def handler(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("Unhandled error", exc_info=(exc_type, exc_value, exc_tb))
        from PySide6.QtWidgets import QApplication, QMessageBox

        signature = (exc_type, str(exc_value))
        if QApplication.instance() is not None and signature not in reported:
            reported.add(signature)
            box = QMessageBox()
            box.setIcon(QMessageBox.Critical)
            box.setWindowTitle(product_title("something went wrong"))
            box.setText("Photo Stats hit an unexpected problem.")
            box.setInformativeText(str(exc_value))
            box.setDetailedText(_format_tb(exc_type, exc_value, exc_tb))
            box.exec()
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = handler


def _format_tb(exc_type, exc_value, exc_tb) -> str:
    """The traceback as text, for the error box's details pane.

    This used to call ``exc_tb.__next__``, which does not exist, so the crash
    reporter crashed while reporting the crash — and the real traceback was
    lost every single time something went wrong.
    """
    import traceback

    return "".join(traceback.format_exception(exc_type, exc_value, exc_tb))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.audit_translations:
        from .i18n import audit

        return 1 if audit() else 0
    paths = Paths()
    logger = setup_logging(paths)

    QCoreApplication.setOrganizationName(ORG_NAME)
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(__version__)
    QApplication.setAttribute(Qt.AA_DontShowIconsInMenus, False)

    app = QApplication(sys.argv[:1])
    # Fonts must be registered before the first widget is built: a widget keeps
    # the font it was constructed with.
    install_fonts()
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")

    config = AppConfig(paths=paths)
    # The language has to be settled before any widget is built, because tr()
    # runs at construction time. Settings win; otherwise follow the OS.
    from .i18n import choose_language

    set_language(choose_language(config.language))
    apply_theme(app, config, logger)

    install_excepthook(logger)
    logger.info("%s %s starting", APP_NAME, __version__)

    from .ui.main_window import MainWindow

    window = MainWindow(config, logger)
    window.show()

    # The window has already reopened the remembered library, or forgotten it
    # and asked, by the time this runs.
    if args.folder:
        QTimer.singleShot(0, lambda: window.open_library(Path(args.folder).expanduser()))

    return app.exec()


def apply_theme(app: QApplication, config: AppConfig, logger: logging.Logger | None = None) -> None:
    theme.apply_base_font(app)
    palette_is_dark = _system_prefers_dark()
    name = config.resolve_theme(palette_is_dark)
    current = theme.THEMES.get(name, theme.DARK)
    app.setPalette(theme.palette(current))
    app.setStyleSheet(theme.combined(current))
    if logger:
        logger.debug("theme=%s (system dark=%s)", name, palette_is_dark)


def _system_prefers_dark() -> bool:
    try:
        scheme = QApplication.styleHints().colorScheme()
        return scheme == Qt.ColorScheme.Dark
    except (AttributeError, TypeError):
        return True
