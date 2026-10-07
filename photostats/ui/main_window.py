"""The main window: folder bar, filters, charts, results — and the glue.

Queries run on a worker thread with a debounce and a generation counter, so the
window never blocks and stale results are discarded instead of flickering.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import threading
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import AUTHOR_URL
from ..core.config import AppConfig
from ..core.exiftool import find_exiftool, install_hint
from ..core.filters import (
    FACET_APERTURE,
    FACET_CAMERA,
    FACET_FOCAL,
    FACET_ISO,
    FACET_LENS,
    Filter,
)
from ..core.indexer import PHASE_EXTRACT, PHASE_WALK, Progress
from ..core.legacy import legacy_candidates
from ..core.queries import PhotoStore
from ..i18n import product_title, tr
from .components.card import Card, Chip, Divider
from .components.folder_bar import FolderBar, _shorten
from .components.footer_link import FooterLink
from .components.timeline import TimelineChart, period_bounds
from .core_filters_bridge import LIST_FACETS
from .panels.filter_panel import FilterPanel
from .panels.photo_list_window import PAGE_SIZE, PhotoListWindow
from .panels.scan_dialog import ScanDialog
from .panels.scan_status import ScanStatus, format_count
from .panels.settings_dialog import SettingsDialog
from .panels.stats_grid import StatsGrid
from .panels.summary import InsightsBar, SummaryTiles, WelcomeScreen
from .scan_worker import LegacyImportWorker, ScanWorker

#: How long a scan may run before the dialog interrupts with its progress.
SCAN_DIALOG_DELAY_MS = 700
#: How long the "finished" dialog stays before getting out of the way.
SCAN_DONE_LINGER_MS = 2500

VALUE_FACETS = (FACET_CAMERA, FACET_LENS, "white_balance", "file_type")


class QueryEmitter(QObject):
    """Carries results back to the GUI thread.

    The emitter lives in the main thread; the worker thread only calls ``emit``,
    which Qt queues onto the main thread automatically.
    """

    done = Signal(int, object)


def run_queries(store: PhotoStore, filters: Filter, sort: str, generation: int,
                emitter: QueryEmitter, with_lists: bool = True, logger=None) -> None:
    """Every read-side query for one filter state, on a worker thread.

    ``with_lists`` controls the sidebar value lists. Those four queries only
    change when a *value* filter changes, so dragging a slider skips them: on a
    six-figure library that is the difference between a snappy refresh and a
    sluggish one.
    """
    from ..core.insights import Insights
    from .core_filters_bridge import CHART_FACETS

    try:
        totals = store.totals(filters)
        payload = {
            "facets": {f: store.facet(f, filters) for f in CHART_FACETS},
            "timeline": store.timeline(filters),
            "totals": totals,
        }
        # The camera facet is cross-filtered — with a camera picked it keeps
        # counting every body so the chart can show the alternatives — so its
        # bucket count is the library's, not the selection's. The tile says
        # how many cameras the shown photos use, so it needs the scoped
        # number, which is only a different query when the filter is set.
        payload["cameras_used"] = (
            len(store.facet(FACET_CAMERA, filters, omit_self=False).buckets)
            if filters.cameras
            else len(payload["facets"][FACET_CAMERA].buckets)
        )
        if with_lists:
            payload["lists"] = {
                facet: store.distinct(column, filters, omit=facet)
                for facet, column in LIST_FACETS.items()
            }
        payload["insights"] = Insights(store, filters, facets=payload["facets"]).build()
        payload["row_total"] = totals.matched
    except Exception as exc:  # never let a failed query kill the window
        if logger:
            logger.exception("query failed")
        payload = {"error": str(exc)}
    finally:
        store.close()
    emitter.done.emit(generation, payload)


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, logger) -> None:
        super().__init__()
        self.config = config
        self.logger = logger
        self.store: PhotoStore | None = None
        self.filters: Filter = Filter()
        self.status_label: QLabel | None = None
        self.cache_label: QLabel | None = None
        self.library: Path | None = None
        self.db_path: Path | None = None
        self.scan_worker: ScanWorker | None = None
        self.import_worker: LegacyImportWorker | None = None
        self._query_thread: threading.Thread | None = None
        self._query_emitter = QueryEmitter()
        self._query_emitter.done.connect(self._on_results)
        self._photo_window: PhotoListWindow | None = None
        self._list_offset = 0
        self._scan_dialog_shown = False
        #: Value-filter state the sidebar lists were last fetched for.
        self._lists_signature = None
        #: Bumped whenever the indexed data changes, invalidating cached lists.
        self._data_version = 0
        self._generation = 0
        self._sort = "date_desc"
        self._offset = 0
        self._scanning = False
        self._query_pending = False
        #: What the footer says when there is more to say than the photo count.
        self._footer_note = ""

        self.resize(1360, 880)
        self.setAcceptDrops(True)
        self.theme = self._theme()

        # Read the remembered library through the config, which forgets it if
        # the folder has gone. Doing this here rather than in main() means the
        # window heals itself however it was constructed, instead of relying on
        # every caller to remember to check.
        remembered = self.config.library
        self.library = Path(remembered) if remembered else None

        self._build_ui()
        self._build_shortcuts()
        if self.library is not None:
            self.open_library(self.library, quietly=True)
        else:
            self._show_welcome()
        QTimer.singleShot(0, self._offer_legacy_import)

    # -- construction ------------------------------------------------------
    def _theme(self):
        """The theme in effect, following the system when set to 'system'."""
        from ..app import _system_prefers_dark
        from . import theme as thememodule

        name = self.config.resolve_theme(_system_prefers_dark())
        return thememodule.THEMES.get(name, thememodule.DARK)

    def _build_ui(self) -> None:
        # Set here, not in __init__, so switching language re-reads the title.
        self.setWindowTitle(product_title())
        """Create the widget tree. Called again after a theme change."""
        old = self.centralWidget()
        if old is not None:
            old.setParent(None)
            old.deleteLater()

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # -- header: which folder, and what the app is doing right now -------
        self.header = QWidget()
        header_layout = QVBoxLayout(self.header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        header_layout.setSpacing(4)

        self.folder_bar = FolderBar(self.theme)
        self.folder_bar.set_recents(self.config.recents)
        self.folder_bar.folder_chosen.connect(self._on_folder_chosen)
        self.folder_bar.rescan_requested.connect(lambda: self._start_scan(force=True))
        self.folder_bar.scan_cancelled.connect(self._cancel_scan)
        self.folder_bar.settings_requested.connect(self._open_settings)
        self.folder_bar.theme_toggled.connect(self._toggle_theme)
        header_layout.addWidget(self.folder_bar)

        self.scan_dialog = ScanDialog(self.theme, self)
        self.scan_dialog.cancel_requested.connect(self._cancel_scan)
        self.scan_dialog.background_requested.connect(lambda: None)

        # Always present, so a scan can never be invisible.
        self.scan_status = ScanStatus(self.theme)
        header_layout.addWidget(self.scan_status)
        layout.addWidget(self.header)
        layout.addWidget(Divider(self.theme))

        # -- body: filters on the left, everything else on the right ---------
        self.filter_panel = FilterPanel(self.theme)
        self.filter_panel.filters_changed.connect(self._on_filters_changed)
        self.filter_panel.clear_requested.connect(self._clear_filters)
        self.filter_panel.preset_requested.connect(self._apply_preset)
        self.filter_panel.setObjectName("sidebar")
        self.filter_panel.setStyleSheet(f"QWidget#sidebar {{ background: {self.theme.bg_alt}; }}")
        self.filter_panel.setFixedWidth(300)

        self.content = QWidget()
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(16, 12, 16, 12)
        content_layout.setSpacing(12)

        # At-a-glance numbers before any chart. The tiles and the insights are
        # one block at the top: the figures first, then the sentences that read
        # them. The insights used to sit between the timeline and the charts,
        # which buried the page's conclusion in the middle of it.
        self.tiles = SummaryTiles(self.theme)
        content_layout.addWidget(self.tiles)
        self.insights = InsightsBar(self.theme)
        content_layout.addWidget(self.insights)

        self.timeline = TimelineChart(self.theme)
        self.timeline.range_selected.connect(self._on_timeline_range)
        self.timeline.cleared.connect(self._clear_date_filter)
        timeline_card = Card(self.theme)
        timeline_layout = QVBoxLayout(timeline_card)
        # Same margins and spacing as a chart card, so the two kinds of card
        # are visibly the same object rather than two similar ones.
        timeline_layout.setContentsMargins(14, 12, 14, 12)
        timeline_layout.setSpacing(8)
        timeline_head = QHBoxLayout()
        self.timeline_caption = QLabel(tr("Timeline"))
        self.timeline_caption.setObjectName("cardTitle")
        timeline_head.addWidget(self.timeline_caption)
        timeline_head.addStretch(1)
        self.timeline_hint = QLabel(tr("drag to select · double-click to clear"))
        self.timeline_hint.setObjectName("hint")
        timeline_head.addWidget(self.timeline_hint)
        timeline_layout.addLayout(timeline_head)
        timeline_layout.addWidget(self.timeline)
        # Every chart card carries a footer saying what it is showing; the
        # timeline did not, so the grid below looked like it was part of a
        # different page.
        self.timeline_foot = QLabel("")
        self.timeline_foot.setObjectName("hint")
        timeline_layout.addWidget(self.timeline_foot)

        # Charts fill the rest; this is the only part that scrolls, and only
        # when the window is too short to show them all. The timeline scrolls
        # with them: a scroll area reserving a scrollbar beside a pinned card
        # made the chart cards a scrollbar's width narrower than it and the
        # columns never lined up. One viewport, one width, every box flush.
        self.charts_host = QWidget()
        charts_layout = QVBoxLayout(self.charts_host)
        charts_layout.setContentsMargins(0, 0, 0, 0)
        charts_layout.setSpacing(12)
        charts_layout.addWidget(timeline_card)

        self.chip_row = QWidget()
        self.chip_layout = QHBoxLayout(self.chip_row)
        self.chip_layout.setContentsMargins(0, 0, 0, 0)
        self.chip_layout.setSpacing(8)
        self.chip_row.setVisible(False)
        charts_layout.addWidget(self.chip_row)

        self.stats_grid = StatsGrid(self.theme)
        self.stats_grid.bar_clicked.connect(self._on_bar_clicked)
        self.stats_grid.selection_cleared.connect(self._on_chart_selection_cleared)
        charts_layout.addWidget(self.stats_grid)
        charts_layout.addStretch(1)

        self.charts_scroll = QScrollArea()
        self.charts_scroll.setWidgetResizable(True)
        self.charts_scroll.setFrameShape(QScrollArea.NoFrame)
        self.charts_scroll.setWidget(self.charts_host)
        content_layout.addWidget(self.charts_scroll, 1)

        # -- footer: what the filter matches, and the way to the files -------
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.match_note = QLabel("")
        self.match_note.setObjectName("hint")
        footer.addWidget(self.match_note)
        footer.addStretch(1)
        self.show_photos = QPushButton(tr("Show photos"))
        self.show_photos.setObjectName("primary")
        self.show_photos.setCursor(Qt.PointingHandCursor)
        self.show_photos.clicked.connect(self._open_photo_list)
        footer.addWidget(self.show_photos)
        content_layout.addLayout(footer)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self.filter_panel)
        body_layout.addWidget(Divider(self.theme, horizontal=False))
        body_layout.addWidget(self.content, 1)

        self.stack = QStackedWidget()
        self.welcome = WelcomeScreen(self.theme, self._browse_folder)
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(body)
        layout.addWidget(self.stack, 1)

        self.setCentralWidget(central)

        if not self.status_label:
            self.status_label = QLabel("")
            self.status_label.setObjectName("statusText")
            self.cache_label = QLabel("")
            self.cache_label.setObjectName("statusMeta")
            self.setStatusBar(QStatusBar())
            self.setStyleSheet(self.styleSheet())
            self.statusBar().setContentsMargins(16, 4, 16, 6)
            self.statusBar().addWidget(self.status_label, 1)
            # The three right-hand items were crammed together with no gap, so
            # the cache location and the attribution read as one run-on string.
            self.statusBar().addPermanentWidget(self._status_spacer(18))
            self.statusBar().addPermanentWidget(self.cache_label)
            self.statusBar().addPermanentWidget(self._status_spacer(14))
            # Attribution last, so it is the one fixed thing in the corner
            # whatever else the status line is saying.
            self.byline = FooterLink(tr("Developed by picstome.com"), AUTHOR_URL,
                                     self.theme, self)
            self.byline.open_failed.connect(self._on_link_failed)
            self.statusBar().addPermanentWidget(self.byline)

        self.scan_status.set_idle()

    def _build_shortcuts(self) -> None:
        def add(sequence: str, handler) -> None:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(handler)

        add("Ctrl+O", self._browse_folder)
        add("Cmd+O", self._browse_folder)
        add("Ctrl+R", lambda: self._start_scan(force=True))
        add("Cmd+R", lambda: self._start_scan(force=True))
        add("Ctrl+,", self._open_settings)
        add("Ctrl+Shift+L", self._toggle_theme)
        add("Esc", self._clear_filters)
        add("Ctrl+Backspace", self._clear_filters)

    # -- library opening ---------------------------------------------------
    def _show_welcome(self) -> None:
        self.stack.setCurrentWidget(self.welcome)

    def _forget_library(self, folder: Path) -> None:
        """Stop showing a library that has gone, and go back to asking for one.

        A path that does not exist is never the open library unless it is the
        one that was remembered, so a bad path from the command line or a drag
        must not close the library already on screen.
        """
        remembered = str(self.config.settings.value("library", "") or "")
        if remembered == str(folder):
            self.config.set_library(None)
        self.config.forget_missing()
        self.folder_bar.set_recents(self.config.recents)

        if self.library is not None and self.library != folder:
            return

        self.library = None
        self.db_path = None
        self._close_store()
        self.folder_bar.set_folder(None)
        self.filter_panel.clear()
        self.stats_grid.clear()
        self.tiles.update_summary(matched=0, total=0, cameras=0, span="—")
        self._show_welcome()

    def _on_folder_chosen(self, folder: str) -> None:
        if folder == "__browse__":
            self._browse_folder()
            return
        self.open_library(Path(folder))

    def _browse_folder(self) -> None:
        start = str(self.library) if self.library else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose a photo folder", start)
        if folder:
            self.open_library(Path(folder))

    def open_library(self, folder: Path, quietly: bool = False) -> None:
        """Open a library, or ask for one if it is not there.

        A folder that has gone missing is not an error worth a dialog. It is
        either the remembered library — in which case the app should simply ask
        again, exactly as it does on a first run — or a path someone just gave
        it, which is worth a line in the status bar and nothing more.
        """
        folder = Path(folder).expanduser()
        if not folder.is_dir():
            if quietly:
                self._forget_library(folder)
                return
            self._forget_library(folder)
            self.scan_status.set_idle()
            self.status_label.setText(
                tr("{folder} is not a folder any more", folder=str(folder))
            )
            return
        if not find_exiftool(self.config.exiftool_path or None):
            self._show_exiftool_missing()

        self.library = folder
        # Opening a library always starts from a clean slate. Carrying the last
        # folder's filters into the next one is confusing — the numbers on
        # screen would be for photos you are no longer looking at, with no
        # obvious way to tell why.
        self.filters = Filter()
        self._offset = 0
        self.filter_panel.apply(self.filters)
        self.config.set_library(folder)
        self.folder_bar.set_recents(self.config.recents)
        self.folder_bar.set_folder(folder)
        self.stack.setCurrentIndex(1)

        self.db_path = self.config.db_path(folder)
        self._close_store()
        from ..core.db import init_db

        try:
            init_db(self.db_path)
            self.store = PhotoStore(self.db_path)
        except Exception as exc:
            self.logger.error("could not open %s: %s", self.db_path, exc)
            QMessageBox.critical(self, "Cannot open the cache", str(exc))
            return

        self._data_version += 1
        self.store.invalidate_cache()
        self.filter_panel.set_bounds(self.store.ranges())
        self._offer_legacy_import()
        self._refresh(force=True)
        self._start_scan()

    def _close_store(self) -> None:
        if self.store is not None:
            self.store.close()
            self.store = None

    # -- scanning ----------------------------------------------------------
    def _start_scan(self, force: bool = False) -> None:
        if self._scanning or self.library is None or self.db_path is None:
            return
        self._scanning = True
        self.folder_bar.set_scanning(True)
        self.scan_status.progress = Progress(phase=PHASE_WALK)
        self.scan_status.set_scanning(Progress(phase=PHASE_WALK))
        # A rescan of an unchanged library finishes in a fraction of a second;
        # showing the dialog immediately would just flash it. Wait a moment and
        # only interrupt if the scan is still going.
        self._scan_dialog_shown = False
        QTimer.singleShot(SCAN_DIALOG_DELAY_MS, self._reveal_scan_dialog)
        self.scan_worker = ScanWorker(self.db_path, self.library, self.config, self)
        self.scan_worker.progress.connect(self._on_progress)
        self.scan_worker.log.connect(self._on_scan_log)
        self.scan_worker.finished_scan.connect(self._on_scan_finished)
        self.scan_worker.start()

    def _close_scan_dialog(self) -> None:
        if not self._scanning:
            self.scan_dialog.hide()

    def _reveal_scan_dialog(self) -> None:
        """Show the dialog, unless the scan already finished.

        A rescan of an unchanged library takes a fraction of a second; popping a
        dialog for that is noise, so the dialog only appears if the scan is still
        running half a second in.
        """
        if self._scanning and self.scan_worker is not None and self.scan_worker.isRunning():
            self._scan_dialog_shown = True
            self.scan_dialog.begin()
            self.scan_dialog.update_progress(self.scan_status.progress)

    def _cancel_scan(self) -> None:
        if self.scan_worker is not None:
            self.scan_worker.cancel()
            self.scan_status.set_scanning(Progress(phase=PHASE_EXTRACT, pending=1))

    def _on_progress(self, progress) -> None:
        self._footer_note = ""
        self.scan_status.set_scanning(progress)
        self.scan_dialog.update_progress(progress)

    def _on_scan_log(self, message: str) -> None:
        self.logger.info(message)
        self.status_label.setText(message)

    def _on_scan_finished(self, result) -> None:
        self._scanning = False
        self.folder_bar.set_scanning(False)
        self.scan_worker = None
        if result.paused:
            self.scan_status.set_paused(tr("Press Scan to carry on where it stopped"))
            if self._scan_dialog_shown:
                self.scan_dialog.show_paused("Everything read so far has been saved.")
            return
        if not result.ok:
            self.scan_status.set_error(result.message or "The scan could not finish")
            self.scan_dialog.close()
            QMessageBox.critical(self, tr("Scan failed"), result.message or tr("Unknown error"))
            return
        # Only now do we know the library's real extremes; open_library ran
        # against an empty database.
        self.filter_panel.set_bounds(self.store.ranges())
        self.scan_status.set_finished(
            tr("Index up to date"),
            f"{result.summary} · exiftool {result.exiftool}" if result.exiftool else result.summary,
        )
        # The line lives in the footer from here on; the header goes back to a
        # single band instead of permanently restating what the footer says.
        self.scan_status.setVisible(False)
        self._footer_note = self.scan_status.text()
        self.status_label.setText(self._footer_note)
        if self._scan_dialog_shown:
            self.scan_dialog.show_finished(result.summary, result.exiftool)
            QTimer.singleShot(SCAN_DONE_LINGER_MS, self._close_scan_dialog)
        self._data_version += 1
        self.store.invalidate_cache()
        self._refresh(force=True)

    # -- queries -----------------------------------------------------------
    def _refresh(self, force: bool = False) -> None:
        """Re-run every query for the current filter, off the GUI thread."""
        if self.store is None:
            return
        self._generation += 1
        self._offset = 0
        if self._query_thread is not None and self._query_thread.is_alive():
            # One worker at a time; this request is served as soon as the
            # running one finishes, and the stale result is dropped.
            self._query_pending = True
            return
        self._start_query()

    def _start_query(self) -> None:
        self._query_pending = False
        generation = self._generation
        # The lists depend on the value filters, not on the
        # numeric ranges, so skip them unless one of those changed. The stored
        # signature only advances once a result is actually applied, so a query
        # that gets superseded still leaves the lists pending.
        with_lists = self._value_signature() != self._lists_signature
        store = self.store.forked()
        thread = threading.Thread(
            target=run_queries,
            args=(store, self.filters, self._sort, generation, self._query_emitter,
                  with_lists, self.logger),
            name="photostats-query",
            daemon=True,
        )
        self._query_thread = thread
        thread.start()

    @staticmethod
    def _safe_join(root: Path, rel_path: str) -> Path | None:
        """Join *rel_path* onto *root*, refusing anything that escapes it.

        rel_path comes from the database, which is portable: a cache copied from
        another machine could carry a path that points outside the library.
        """
        if not rel_path or rel_path.startswith("/") or "\\" in rel_path:
            return None
        target = (root / rel_path).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            return None
        return target

    def _value_signature(self):
        """The part of the filter the sidebar lists depend on.

        Includes a data version so that a finished scan invalidates them: the
        query that runs when a library is first opened sees an empty database,
        and without this its (empty) result would suppress the lists forever.
        """
        filters = self.filters
        return (
            self._data_version,
            filters.cameras, filters.lenses, filters.white_balance,
            filters.file_types, filters.search, filters.date_from, filters.date_to,
            filters.flash,
        )

    def _on_results(self, generation: int, payload) -> None:
        """Runs in the GUI thread: apply the newest result, then reap the worker."""
        self._query_thread = None
        retry = self._query_pending
        if generation != self._generation or self.store is None:
            if retry:
                QTimer.singleShot(0, self._start_query)
            return  # superseded by a newer filter change

        if "error" in payload:
            self.insights.set_message(f"Could not read the statistics: {payload['error']}")
            self.scan_status.set_error(payload["error"])
            if retry:
                QTimer.singleShot(0, self._start_query)
            return

        facets, totals, timeline = payload["facets"], payload["totals"], payload["timeline"]
        self.stats_grid.update_results(facets, payload["insights"], self.filters)
        self.timeline.set_timeline(timeline, (self.filters.date_from, self.filters.date_to))
        points = timeline.points
        self.timeline_caption.setText(
            f"{tr('Timeline')} · {timeline.label}"
            + (f" · {points[0][0]:%b %Y} – {points[-1][0]:%b %Y}" if points else "")
        )
        if self.filters.date_from or self.filters.date_to:
            span = tr("Showing {count} photos",
                      count=format_count(totals.matched))
        else:
            span = tr("{count} photos over the whole library",
                      count=format_count(totals.total))
        self.timeline_foot.setText(span)
        self.insights.set_insights(self.stats_grid.insights())
        self._update_tiles(totals, facets, payload.get("cameras_used"))
        self._matched_total = payload["row_total"]

        if "lists" in payload:
            self._update_filter_lists(payload["lists"])
            self._lists_signature = self._value_signature()
        self._rebuild_chips()
        if retry:
            QTimer.singleShot(0, self._start_query)

    def _update_tiles(self, totals, facets, cameras_used: int | None = None) -> None:
        """The four figures at the top of the page."""
        span = "—"
        if self.timeline.timeline and self.timeline.timeline.points:
            points = self.timeline.timeline.points
            span = f"{points[0][0]:%Y} – {points[-1][0]:%Y}"
        elif totals.matched:
            span = "undated"
        if cameras_used is None:
            # Older payloads carry only the cross-filtered facets.
            camera_facet = facets.get("camera")
            cameras_used = len(camera_facet.buckets) if camera_facet else 0
        self.tiles.update_summary(
            matched=totals.matched,
            total=totals.total,
            cameras=cameras_used,
            span=span,
        )
        if self.filters.is_empty:
            note = tr("{count} photos · nothing filtered",
                      count=format_count(totals.matched))
        else:
            note = tr("{matched} of {total} photos match",
                      matched=format_count(totals.matched),
                      total=format_count(totals.total))
        self.match_note.setText(note)
        self.show_photos.setText(tr("Show {count} photos", count=format_count(totals.matched)))
        self.show_photos.setEnabled(totals.matched > 0)
        self.show_photos.setVisible(totals.matched > 0)
        # The scan line outranks the generic note: "1,126 from cache" is more
        # useful than "1,126 of 1,126 photos match" once a scan has finished.
        self.status_label.setText(self._footer_note or note)
        if self.db_path and self.cache_label:
            # Capped: an unbounded path here would eat the status line on the
            # left and, eventually, the attribution in the corner. The cache
            # location is the least important thing in the bar.
            self.cache_label.setText(
                f"{self.db_path.name} · {_shorten(str(self.db_path.parent), 58)}"
            )

    def _update_filter_lists(self, lists: dict) -> None:
        """Refresh the sidebar value lists, keeping the current selection."""
        for facet, values in lists.items():
            checklist = getattr(self.filter_panel, f"list_{facet}", None)
            if checklist is None:
                continue
            peak = max((count for _value, count in values), default=0) or 1
            selected = set(checklist.selected_values())
            checklist.set_values(
                [(value, count, count / peak) for value, count in values], selected
            )
        self.filter_panel.apply(self.filters)

    # -- filters -----------------------------------------------------------
    def _on_filters_changed(self, filters: Filter) -> None:
        self.filters = filters
        self._offset = 0
        self._refresh()
        self.stats_grid.set_selected(filters)

    def _on_bar_clicked(self, facet: str, label: str) -> None:
        """A bar was clicked: toggle that value, unless shift narrows to it."""
        from dataclasses import replace

        modifiers = QApplication.keyboardModifiers()
        if facet in VALUE_FACETS:
            values = set(getattr(self.filters, _attribute_for(facet)))
            values = {label} if modifiers & Qt.ShiftModifier else values ^ {label}
            self.filters = replace(self.filters, **{_attribute_for(facet): frozenset(values)})
        elif facet == FACET_ISO:
            self.filters = replace(self.filters, iso_min=float(label), iso_max=float(label))
        elif facet == FACET_APERTURE:
            value = float(label.lstrip("f/"))
            self.filters = replace(self.filters, aperture_min=value, aperture_max=value)
        elif facet == "shutter":
            value = _shutter_value(label)
            self.filters = replace(self.filters, shutter_min=value, shutter_max=value)
        elif facet == FACET_FOCAL:
            value = _to_number(label.replace("mm", ""))
            self.filters = replace(self.filters, focal_min=value, focal_max=value)
        else:
            return
        self._offset = 0
        self.filter_panel.apply(self.filters)
        self.stats_grid.set_selected(self.filters)
        self._refresh()

    def _on_chart_selection_cleared(self, facet: str) -> None:
        """The badge was clicked: drop that facet's filter and keep the rest."""
        from dataclasses import replace

        if facet in VALUE_FACETS:
            self.filters = replace(
                self.filters, **{_attribute_for(facet): frozenset()})
        elif facet == FACET_ISO:
            self.filters = replace(self.filters, iso_min=None, iso_max=None)
        elif facet == FACET_APERTURE:
            self.filters = replace(self.filters, aperture_min=None, aperture_max=None)
        elif facet == "shutter":
            self.filters = replace(self.filters, shutter_min=None, shutter_max=None)
        elif facet == FACET_FOCAL:
            self.filters = replace(self.filters, focal_min=None, focal_max=None)
        else:
            return
        self._offset = 0
        self.filter_panel.apply(self.filters)
        self.stats_grid.set_selected(self.filters)
        self._refresh()

    def _on_timeline_range(self, start, end) -> None:
        from dataclasses import replace

        granularity = self.timeline.timeline.granularity if self.timeline.timeline else "month"
        filters = replace(
            self.filters,
            date_from=period_bounds(start, granularity)[0] if start else None,
            date_to=period_bounds(end, granularity)[1] if end else None,
        )
        self.filters = filters
        self._offset = 0
        self.filter_panel.apply(filters)
        self._refresh()

    def _clear_date_filter(self) -> None:
        from dataclasses import replace

        self.filters = replace(self.filters, date_from=None, date_to=None)
        self._offset = 0
        self.filter_panel.apply(self.filters)
        self._refresh()

    def _apply_preset(self, key: str) -> None:
        from dataclasses import replace

        today = date.today()
        if key == "this_year":
            filters = replace(self.filters, date_from=date(today.year, 1, 1), date_to=today)
        elif key == "last_12":
            filters = replace(self.filters, date_from=today - timedelta(days=365), date_to=today)
        elif key == "last_30":
            filters = replace(self.filters, date_from=today - timedelta(days=30), date_to=today)
        else:
            filters = replace(self.filters, date_from=None, date_to=None)
        self.filters = filters
        self._offset = 0
        self.filter_panel.apply(filters)
        self._refresh()

    def _clear_filters(self) -> None:
        from dataclasses import replace

        keep = self.filters.include_no_date
        self.filters = replace(Filter(), include_no_date=keep)
        self._offset = 0
        self.filter_panel.apply(self.filters)
        self.stats_grid.set_selected(self.filters)
        self._refresh()

    def _rebuild_chips(self) -> None:

        while self.chip_layout.count():
            item = self.chip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        chips: list[tuple[str, str, str]] = []
        if self.filters.date_from or self.filters.date_to:
            start = self.filters.date_from.isoformat() if self.filters.date_from else "…"
            end = self.filters.date_to.isoformat() if self.filters.date_to else "…"
            chips.append(("date", "Date", f"{start} → {end}"))
        if self.filters.include_no_date:
            chips.append(("include_no_date", "No EXIF date", "included"))
        for facet in VALUE_FACETS:
            values = sorted(getattr(self.filters, _attribute_for(facet)))
            for value in values[:4]:
                chips.append((f"{facet}:{value}", facet.replace("_", " ").title(), value))
            if len(values) > 4:
                chips.append((facet, facet.replace("_", " ").title(), f"+{len(values) - 4} more"))
        for name, low_attr, high_attr, label in (
            (FACET_ISO, "iso_min", "iso_max", "ISO"),
            ("shutter", "shutter_min", "shutter_max", "Shutter"),
            (FACET_APERTURE, "aperture_min", "aperture_max", "Aperture"),
            (FACET_FOCAL, "focal_min", "focal_max", "Focal"),
        ):
            low, high = getattr(self.filters, low_attr), getattr(self.filters, high_attr)
            if low is not None or high is not None:
                chips.append((name, label, f"{_fmt(low, name)} – {_fmt(high, name)}"))
        if self.filters.flash != "any":
            chips.append(("flash", "Flash", self.filters.flash.replace("_", " ")))

        for key, label, value in chips:
            chip = Chip(self.theme, label, value)
            chip.removed.connect(lambda k=key: self._remove_chip(k))
            self.chip_layout.addWidget(chip)
        self.chip_layout.addStretch(1)
        self.chip_row.setVisible(bool(chips))

    def _remove_chip(self, key: str) -> None:
        from dataclasses import replace

        if ":" in key:
            facet, value = key.split(":", 1)
            attribute = _attribute_for(facet)
            values = set(getattr(self.filters, attribute))
            values.discard(value)
            self.filters = replace(self.filters, **{attribute: frozenset(values)})
        elif key == "date":
            self.filters = replace(self.filters, date_from=None, date_to=None)
        elif key == "include_no_date":
            self.filters = replace(self.filters, include_no_date=False)
        elif key in ("cameras", "lenses"):
            self.filters = replace(self.filters, **{key: frozenset()})
        elif key == "flash":
            self.filters = replace(self.filters, flash="any")
        else:
            self.filters = replace(
                self.filters,
                iso_min=None, iso_max=None, shutter_min=None, shutter_max=None,
                aperture_min=None, aperture_max=None, focal_min=None, focal_max=None,
            )
        self._offset = 0
        self.filter_panel.apply(self.filters)
        self.stats_grid.set_selected(self.filters)
        self._refresh()

    # -- results -----------------------------------------------------------
    def _on_sort_changed(self, sort: str) -> None:
        self._sort = sort
        self._refresh_photo_list()

    def _open_photo_list(self) -> None:
        """Open the matching photos in their own window, on demand."""
        if self.store is None:
            return
        if self._photo_window is None:
            self._photo_window = PhotoListWindow(self.theme, self)
            self._photo_window.sort_changed.connect(self._on_sort_changed)
            self._photo_window.more_requested.connect(self._load_more)
            self._photo_window.revealed.connect(self._reveal_path)
        self._photo_window.show()
        self._photo_window.raise_()
        self._photo_window.activateWindow()
        self._refresh_photo_list()

    def _refresh_photo_list(self) -> None:
        """Reload the list window from the first page, if it is open."""
        if self._photo_window is None or not self._photo_window.isVisible():
            return
        if self.store is None:
            return
        try:
            rows, total = self.store.results(self.filters, sort=self._sort, limit=PAGE_SIZE)
        except Exception as exc:
            self.logger.error("could not read the photo list: %s", exc)
            return
        self._photo_window.set_rows(rows, total, _describe_filters(self.filters))

    def _load_more(self) -> None:
        """Append the next page to the list window."""
        if self._photo_window is None or self.store is None:
            return
        # Page from however many rows are on screen, so the next page continues
        # exactly where the window stops.
        offset = len(self._photo_window.model.rows)
        try:
            rows, total = self.store.results(
                self.filters, sort=self._sort, limit=PAGE_SIZE, offset=offset
            )
        except Exception as exc:
            self.logger.error("could not load more rows: %s", exc)
            return
        if not rows:
            return
        self._photo_window.model.append_rows(rows, total)
        self._photo_window.set_rows(self._photo_window.model.rows, total)

    def _reveal_path(self, rel_path: str) -> None:
        target = self._safe_join(self.library, rel_path) if self.library else None
        if target is None:
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(target)])


    # -- dialogs -----------------------------------------------------------
    def _show_exiftool_missing(self) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(tr("exiftool is required"))
        box.setText(tr("Photo Stats needs exiftool to read photo metadata."))
        box.setInformativeText(f"Install it with:\n\n    {install_hint()}\n\n"
                               f"then press Scan again.")
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()

    def _open_settings(self) -> None:
        from ..i18n import choose_language, set_language

        dialog = SettingsDialog(self.config, self.theme, self)
        if dialog.exec():
            dialog.apply_to_config()
            if self.library is not None:
                self.db_path = self.config.db_path(self.library)
            # A new language, or any explicit theme choice, needs a new tree:
            # widgets bake in their strings and colours as they are built.
            set_language(choose_language(self.config.language))
            self._rebuild_ui()

    def _toggle_theme(self) -> None:
        """Flip between light and dark, then rebuild around the new palette."""
        self.config.set_theme("light" if self.theme.is_dark else "dark")
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        """Rebuild the widget tree and restore state around it.

        Both a theme change and a language change land here: widgets bake in
        their colours and their strings as they are constructed, so there is
        nothing reliable to retranslate or restyle in place.
        """
        from ..app import apply_theme

        apply_theme(QApplication.instance(), self.config, self.logger)
        self.theme = self._theme()
        if self.byline is not None:
            self.byline.set_theme(self.theme)
        if self.folder_bar is not None:
            self.folder_bar.set_theme(self.theme)
        if self._photo_window is not None:
            self._photo_window.close()
            self._photo_window = None
        self.scan_dialog.close()
        self._build_ui()
        self.folder_bar.set_folder(self.library)
        self.folder_bar.set_scanning(self._scanning)
        if self.library is not None:
            self.open_library(self.library)
        else:
            self._show_welcome()
            self.stats_grid.clear()
        self.refresh()

    @staticmethod
    def _status_spacer(width: int) -> QWidget:
        """A fixed gap between the status bar's right-hand items."""
        spacer = QWidget()
        spacer.setFixedWidth(width)
        return spacer

    def _on_link_failed(self, url: str) -> None:
        """No browser to hand the link to: say so instead of doing nothing."""
        self.status_label.setText(FooterLink.failure_message(url))

    def refresh(self) -> None:
        """Re-run the queries (after a theme change, for example)."""
        self._refresh(force=True)

    # -- legacy cache ------------------------------------------------------
    def _offer_legacy_import(self) -> None:
        legacy = legacy_candidates(self.library)
        if not legacy or self.db_path is None:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(tr("Reuse an existing index?"))
        box.setText(tr("A cache from the original Photo Stats script was found."))
        box.setInformativeText(
            f"{legacy}\n\nImport it? That skips re-reading every photo and takes seconds "
            "instead of hours. Nothing in that file is modified."
        )
        yes = box.addButton("Import", QMessageBox.AcceptRole)
        box.addButton("Ignore", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            self._start_legacy_import(legacy)

    def _start_legacy_import(self, legacy: Path) -> None:
        self.status_label.setText(tr("Importing the old index…"))
        self.import_worker = LegacyImportWorker(legacy, self.db_path, self.library, self)
        self.import_worker.progress.connect(
            lambda count: self.status_label.setText(tr("Imported {count} photos…", count=f"{count:,}"))
        )
        self.import_worker.finished_import.connect(self._on_import_finished)
        self.import_worker.start()

    def _on_import_finished(self, report) -> None:
        self.import_worker = None
        self._data_version += 1
        self.store.invalidate_cache()
        self.status_label.setText(report.summary())
        self.logger.info(report.summary())
        self._refresh(force=True)

    # -- drag and drop -----------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: D102, N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.welcome.set_active(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: D102, N802
        self.welcome.set_active(False)

    def dropEvent(self, event) -> None:  # noqa: D102, N802
        self.welcome.set_active(False)
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_dir():
                self.open_library(path)
                break
            if path.is_file():
                self.open_library(path.parent)
                break
        event.acceptProposedAction()

    # -- shutdown ----------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: D102, N802
        if self._query_thread is not None and self._query_thread.is_alive():
            self._query_thread.join(timeout=3)
        if self.scan_worker is not None and self.scan_worker.isRunning():
            self.scan_worker.cancel()
            self.scan_worker.wait(3000)
        if self.import_worker is not None and self.import_worker.isRunning():
            self.import_worker.wait(3000)
        if self._photo_window is not None:
            self._photo_window.close()
        self.scan_dialog.close()
        if self.store is not None:
            from ..core.db import checkpoint, connect

            with contextlib.suppress(Exception):
                checkpoint(connect(self.db_path))
            self._close_store()
        self.config.sync()
        super().closeEvent(event)


def _describe_filters(filters: Filter) -> str:
    """A short line describing what the list is showing, for the window title."""
    from ..core.export import describe_filters

    return describe_filters(filters, human=True)


def _attribute_for(facet: str) -> str:
    return {
        FACET_CAMERA: "cameras",
        FACET_LENS: "lenses",
        "white_balance": "white_balance",
        "file_type": "file_types",
    }.get(facet, facet)


def _to_number(text: str) -> float:
    from ..core.parse import to_float

    return to_float(text) or 0.0


def _shutter_value(label: str) -> float:
    from ..core.parse import to_float

    if label.startswith("1/"):
        return 1 / float(label[2:])
    return to_float(label) or 0.5


def _fmt(value, facet: str) -> str:
    if value is None:
        return "…"
    from ..core.parse import format_fnumber, format_focal, format_shutter

    if facet == "shutter":
        return format_shutter(value)
    if facet == FACET_APERTURE:
        return format_fnumber(value)
    if facet == FACET_FOCAL:
        return format_focal(value)
    return f"{value:g}"
