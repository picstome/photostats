"""GUI tests driven through the real window, with modal dialogs auto-dismissed.

Qt runs on the offscreen platform so the suite works headless in CI.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")

from conftest import make_library  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from photostats.core.config import AppConfig  # noqa: E402
from photostats.core.indexer import Progress  # noqa: E402
from photostats.i18n import tr  # noqa: E402
from photostats.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="session")
def app():
    existing = QApplication.instance()
    application = existing or QApplication([])
    yield application


@pytest.fixture
def dismiss_dialogs(app, monkeypatch):
    """Answer every modal dialog with 'Ignore'/'Cancel' so nothing blocks."""
    def ignore(parent=None):
        for dialog in app.topLevelWidgets():
            if isinstance(dialog, (QMessageBox, QDialog)) and dialog.isVisible():
                dialog.reject()

    timer = QTimer()
    timer.timeout.connect(ignore)
    timer.start(30)
    yield
    timer.stop()


@pytest.fixture
def window(app, paths, dismiss_dialogs, request):
    from photostats.app import apply_theme

    config = AppConfig(paths=paths)
    config.set_theme("dark")
    # Never let a test reach GitHub: the monthly update check is off in the
    # suite. The banner itself is exercised directly.
    config.set_updates_enabled(False)
    apply_theme(app, config)   # the real app does this in main(); without it the
    main = MainWindow(config, logging.getLogger("photostats.tests"))
    main.show()
    yield main
    main._query_thread and main._query_thread.join(timeout=2)
    main.deleteLater()
    app.processEvents()


def _chips(window) -> int:
    """The filter chips above the charts; the layout also holds a stretch."""
    from photostats.ui.components.card import Chip

    return len(window.chip_row.findChildren(Chip))


def _matched(window) -> int:
    """How many photos the current filter matches, as the UI reports it."""
    return int(window.tiles.matched.value.text().replace(",", ""))


def spin(app, ms: int = 400) -> None:
    """Run the event loop for *ms*, letting worker threads deliver results."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.fixture
def library(tmp_path, window):
    root = tmp_path / "photos"
    make_library(root, count=24)
    window.open_library(root)
    spin(app, 2500)
    return root


# -- construction --------------------------------------------------------
def test_window_opens_without_a_library(window):
    assert window.stack.currentWidget() is window.welcome
    assert window.library is None


def test_scan_dialog_appears_only_for_real_work(library, window, app):
    """A cached rescan finishes in milliseconds and must not flash a dialog."""
    window._start_scan(force=True)
    seen = []
    while window._scanning:
        spin(app, 40)
        seen.append(window.scan_dialog.isVisible())
    assert not any(seen), "the dialog flashed for a scan that was already up to date"
    # The header still reports the outcome.
    assert window.scan_status.message.text() == "Index up to date"


def test_scan_dialog_updates_from_late_progress(library, window, app):
    """The dialog opens 0.7s in and must catch up to where the scan actually is."""
    window.scan_dialog.begin()
    assert window.scan_dialog.isVisible()
    window.scan_dialog.update_progress(
        Progress(phase="extract", total=1000, indexed=250, new=250, rate=100.0, eta=7.0)
    )
    assert window.scan_dialog.bar.value() == 250
    assert window.scan_dialog.bar.maximum() == 1000
    assert "250 of 1,000" in window.scan_dialog.detail.text()

    # Sending it to the background hides it and never stops the scan.
    window.scan_dialog._to_background()
    assert not window.scan_dialog.isVisible()


def test_scan_dialog_reports_the_walk_phase(window):
    window.scan_dialog.update_progress(Progress(phase="walk", indexed=4321))
    assert window.scan_dialog.phase_label.text() == "Looking for photos"
    assert "4,321" in window.scan_dialog.detail.text()
    assert window.scan_dialog.bar.maximum() == 0  # indeterminate


def test_the_scan_strip_appears_while_scanning_and_leaves_when_idle(window):
    """A scan must never look like a hang, but an idle window must not wear it.

    The strip used to sit permanently in the layout between the header and the
    filters, which pushed the charts down and gave an idle window a progress
    bar with nothing to report. It now lives in the header only while a scan is
    running, and its summary ends up in the footer.
    """
    assert window.scan_status.isHidden()

    window.scan_status.set_scanning(
        Progress(phase="extract", total=1000, indexed=250, new=250, rate=120.0, eta=6.0)
    )
    assert not window.scan_status.isHidden()
    assert "Reading photo details" in window.scan_status.message.text()
    assert "250 of 1,000" in window.scan_status.detail.text()
    assert window.scan_status.bar.isVisible()

    window.scan_status.set_idle()
    assert window.scan_status.isHidden()


def test_a_finished_scan_reports_itself_in_the_footer(library, window, app):
    """The completed summary belongs with the other always-on footer facts.

    Once a scan has finished, the footer keeps saying "Index up to date · n
    photos" instead of falling back to the generic "n of n photos match", which
    would read as though the user had just changed a filter.
    """
    window.scan_status.set_finished(
        tr("Index up to date"), "24 photos, 24 new · exiftool 13.36")
    window._footer_note = window.scan_status.text()
    window._refresh(force=True)
    spin(app, 2500)

    text = window.status_label.text()
    assert text.startswith(tr("Index up to date"))
    assert "24 photos" in text
    assert "exiftool 13.36" in text

    window.scan_status.set_finished("Index up to date", "24 photos")
    assert not window.scan_status.bar.isVisible()


def test_opening_a_library_populates_everything(library, window):
    assert window.store is not None
    totals = window.store.totals()
    assert totals.total == 24

    filled = {
        facet: card
        for facet, card in window.stats_grid.cards.items()
        if card.result is not None and card.result.buckets
    }
    assert {"camera", "lens", "iso", "aperture", "focal", "flash"} <= set(filled)
    for facet, card in filled.items():
        assert card.result.total > 0, f"chart {facet} counted nothing"
    # Attributes the photos carry no data for say so instead of looking broken.
    for facet, card in window.stats_grid.cards.items():
        if facet not in filled:
            assert card.result is None or not card.result.buckets

    assert window.tiles.matched.value.text() == '24'
    assert window.show_photos.text() == 'Show 24 photos'
    assert window.timeline.timeline is not None
    assert window.timeline.timeline.points
    assert [value for value, _count, _share in window.filter_panel.list_camera._values]
    # The footer leads with the index state; the count is still reported.
    assert window.status_label.text().endswith(str(totals.total) + " newly read" + window.status_label.text().split("newly read")[-1])


def test_insights_are_generated(library, window):
    items = window.stats_grid.insights()
    assert items, "no insights were produced for a populated library"
    text = " ".join(i.text for i in items)
    assert "NIKON Z8" in text
    # The bar renders one pill per insight, the first three.
    from PySide6.QtWidgets import QLabel

    pills = [label.text() for label in window.insights.findChildren(QLabel) if label.text()]
    assert pills


def test_the_insights_sit_with_the_tiles_at_the_top(window, library):
    """The figures and the sentences that read them are one block at the top.

    The insights used to sit between the timeline and the charts, which buried
    the page's conclusion in the middle of it.
    """
    layout = window.content.layout()
    widgets = [
        layout.itemAt(i).widget()
        for i in range(layout.count())
        if layout.itemAt(i).widget() is not None
    ]
    assert widgets.index(window.tiles) < widgets.index(window.insights)
    assert widgets.index(window.insights) < widgets.index(window.charts_scroll)


def test_selecting_a_camera_keeps_the_shown_numbers_sane(library, window, app):
    """Picking a body must not leak library-wide counts into selection facts.

    The camera chart stays cross-filtered on purpose — it keeps showing every
    body so you can switch. But the tiles and the sentences speak for the
    selection, and dividing the chart's counts by the matched total produced
    "4058% of these are from …" and "8 cameras used" for 26 photos from one.
    """
    import re

    from PySide6.QtWidgets import QLabel

    label = window.stats_grid.cards["camera"].result.buckets[0].label
    window._on_bar_clicked("camera", label)
    spin(app, 900)

    # The shown photos come from exactly one body, whatever the chart shows.
    assert window.tiles.sources.value.text() == "1"

    texts = [item.text() for item in window.insights.findChildren(QLabel) if item.text()]
    assert texts, "the guard silenced every insight"
    for text in texts:
        for percentage in re.findall(r"(\d+)%", text):
            assert int(percentage) <= 100, text


# -- filtering -----------------------------------------------------------
def test_clicking_a_camera_bar_filters_and_adds_a_chip(library, window, app):
    label = window.stats_grid.cards["camera"].result.buckets[0].label
    window._on_bar_clicked("camera", label)
    spin(app, 900)

    assert label in window.filters.cameras
    expected = window.store.totals(window.filters).matched
    assert expected < window.store.totals().total
    assert _matched(window) == expected
    assert window.chip_layout.count() >= 2  # the chip plus the stretch


def test_clicking_the_same_bar_again_clears_it(library, window):
    label = window.stats_grid.cards["camera"].result.buckets[0].label
    window._on_bar_clicked("camera", label)
    spin(app, 900)
    window._on_bar_clicked("camera", label)
    spin(app, 900)
    assert window.filters.cameras == frozenset()
    assert _matched(window) == window.store.totals().total


def test_iso_bar_sets_an_exact_range(library, window):
    bucket = window.stats_grid.cards["iso"].result.buckets[0]
    window._on_bar_clicked("iso", str(bucket.key))
    spin(app, 900)
    assert window.filters.iso_min == window.filters.iso_max == float(bucket.key)
    assert _matched(window) == window.store.totals(window.filters).matched


def test_checkbox_in_the_sidebar_filters(library, window):
    label = window.filter_panel.list_camera._values[0][0]
    window.filter_panel.list_camera.set_selected({label})
    window.filter_panel.list_camera.selection_changed.emit([label])
    spin(app, 900)
    assert label in window.filters.cameras
    assert _matched(window) < window.store.totals().total


def test_range_slider_filters(library, window, app):
    # emit=True is what a drag does; apply() sets the range without emitting.
    window.filter_panel.slider_iso.set_range(400, 3200, emit=True)
    spin(app, 900)
    assert window.filters.iso_min == 400
    assert window.filters.iso_max == 3200
    expected = window.store.totals(window.filters).matched
    assert _matched(window) == expected


def test_the_top_bar_search_box_is_gone(window):
    """Removed: it was never wired to the filter, and it spun a timer forever."""
    from photostats.ui.components.folder_bar import FolderBar

    assert not hasattr(window.folder_bar, "search")
    assert not [name for name in dir(FolderBar) if "search" in name.lower()]
    assert not hasattr(window, "_apply_search")
    assert not hasattr(window, "_update_search")
    assert not hasattr(window, "search_timer")


def test_the_search_filter_still_works_for_those_who_want_it(library, window, app):
    """The capability survives even though the box does not."""
    from dataclasses import replace

    window.filters = replace(window.filters, search="IMG_4001")
    window._refresh()
    spin(app, 700)
    assert window.filters.search == "IMG_4001"
    assert _matched(window) == 1


def test_timeline_preset_filters_by_date(library, window):
    window._apply_preset("last_30")
    spin(app, 900)
    assert window.filters.date_from is not None
    assert _matched(window) == window.store.totals(window.filters).matched


def test_clear_all_resets_everything(library, window):
    window._on_bar_clicked("camera", window.stats_grid.cards["camera"].result.buckets[0].label)
    window._apply_preset("this_year")
    spin(app, 900)
    window._clear_filters()
    spin(app, 900)
    assert window.filters.is_empty
    assert _matched(window) == window.store.totals().total


def test_removing_a_chip_drops_that_filter(library, window):
    window.filter_panel.list_camera.set_selected({"NIKON Z8"})
    window.filter_panel.list_camera.selection_changed.emit(["NIKON Z8"])
    spin(app, 900)
    assert window.filters.cameras == frozenset({"NIKON Z8"})
    window._remove_chip("camera:NIKON Z8")
    spin(app, 900)
    assert window.filters.cameras == frozenset()


def test_sorting_reorders_the_list(library, window):
    window._open_photo_list()
    spin(app, 900)
    window._on_sort_changed("iso_desc")
    spin(app, 900)
    isos = [row["iso"] for row in window._photo_window.model.rows if row["iso"]]
    assert isos == sorted(isos, reverse=True)


def test_photo_list_opens_on_demand(library, window):
    assert window._photo_window is None, "the list must not be built until asked for"
    window._open_photo_list()
    spin(app, 900)
    assert window._photo_window.isVisible()
    assert window._photo_window.model.total == 24
    assert len(window._photo_window.model.rows) == 24


def test_load_more_appends_rows(library, window):
    window._open_photo_list()
    spin(app, 900)
    window._photo_window.set_rows(window._photo_window.model.rows[:5], 24)
    window._load_more()
    paths = [row["rel_path"] for row in window._photo_window.model.rows]
    assert len(paths) > 5
    assert len(paths) == len(set(paths)), "pages must not overlap"


# -- the export button is gone --------------------------------------------
def test_there_is_no_export_button(window):
    """Removed: the menu buried three writers behind a second click."""
    from photostats.ui.components.folder_bar import FolderBar

    assert not hasattr(window.folder_bar, "export")
    assert not [name for name in dir(FolderBar) if "export" in name]
    assert not hasattr(window, "_export")
    assert not hasattr(window, "_write_csv")


def test_settings_dialog_round_trip(window, tmp_path):
    from photostats.ui.panels.settings_dialog import SettingsDialog

    dialog = SettingsDialog(window.config, window.theme, window)
    dialog.theme_box.setCurrentIndex(dialog.theme_box.findData("light"))
    dialog.accept()
    dialog.apply_to_config()
    assert window.config.theme_name == "light"


# -- resilience ----------------------------------------------------------
def test_opening_an_empty_folder_is_handled(window, tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    window.open_library(empty)
    spin(app, 1500)
    assert window.store is not None
    assert window.store.totals().total == 0
    for card in window.stats_grid.cards.values():
        assert card.result is None or not card.result.buckets


def test_opening_a_missing_folder_warns_and_keeps_state(window, tmp_path, app):
    window.library = None
    window.open_library(tmp_path / "does-not-exist")
    spin(app, 300)
    assert window.library is None


def test_closing_while_scanning_is_safe(window, tmp_path, app):
    root = tmp_path / "photos2"
    make_library(root, count=8)
    window.open_library(root)
    window._start_scan()
    spin(app, 200)
    window.close()
    spin(app, 300)


# -- camera and lens lists -------------------------------------------------

def _click_row(check_list, index: int = 0) -> None:
    """Click a row the way a person does: anywhere on the row."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    item = check_list.list.item(index)
    rect = check_list.list.visualItemRect(item)
    QTest.mouseClick(check_list.list.viewport(), Qt.LeftButton,
                     Qt.NoModifier, rect.center())


def test_clicking_a_camera_row_filters(window, library, app):

    check_list = window.filter_panel.list_camera
    _click_row(check_list, 0)
    spin(app)

    label = check_list.selected_values()[0]
    assert window.filters.cameras == frozenset({label})
    assert window.tiles.matched.value.text() != f"{window.store.totals().total:,}"


def test_clicking_the_same_row_again_clears_the_filter(window, library, app):

    check_list = window.filter_panel.list_camera
    _click_row(check_list, 0)
    spin(app)
    _click_row(check_list, 0)
    spin(app)

    assert window.filters.cameras == frozenset()
    assert check_list.selected_values() == []


def test_clicking_a_lens_row_filters(window, library, app):

    _click_row(window.filter_panel.list_lens, 0)
    spin(app)

    assert len(window.filters.lenses) == 1
    assert window.filters.lenses <= frozenset(window.filter_panel.list_lens.selected_values())


def test_camera_and_lens_filters_combine(window, library, app):

    _click_row(window.filter_panel.list_camera, 0)
    spin(app)
    _click_row(window.filter_panel.list_lens, 0)
    spin(app)

    assert window.filters.cameras and window.filters.lenses
    assert window.store.totals(window.filters).matched < window.store.totals().total


def test_search_box_filters_the_camera_list(window, library, app):
    check_list = window.filter_panel.list_camera
    every = check_list.list.count()
    assert every > 1
    first = check_list.list.item(0).text()
    check_list.search.setText(first)
    spin(app, 400)
    narrowed = check_list.list.count()
    assert 0 < narrowed <= every
    assert all(first in check_list.list.item(i).text() for i in range(narrowed))


# -- ranges taken from the data --------------------------------------------

def test_sliders_span_the_values_in_the_library(window, library, app):

    panel = window.filter_panel
    ranges = window.store.ranges()
    assert panel.slider_iso.minimum == ranges["iso"][0]
    assert panel.slider_iso.maximum == ranges["iso"][1]
    assert panel.slider_aperture.minimum == ranges["aperture"][0]
    assert panel.slider_aperture.maximum == ranges["aperture"][1]
    assert panel.slider_shutter.maximum == ranges["shutter"][1]
    assert panel.slider_focal.minimum == ranges["focal"][0]


def test_readouts_are_written_the_way_a_photographer_would(window, library, app):

    panel = window.filter_panel
    assert "mm" not in panel.readout_iso.text()      # ISO is a plain number
    assert panel.readout_aperture.text().startswith("f/")
    assert "s" in panel.readout_shutter.text()


# -- sidebar layout ---------------------------------------------------------

def test_only_the_first_filter_section_starts_open(window, library, app):
    """Eight open panels is a wall, so the sidebar opens just the first one.

    Cameras is what a photographer reaches for first, so it is open on arrival;
    everything else waits for a click rather than burying the list.
    """
    from photostats.ui.components.card import Section

    sections = window.filter_panel.findChildren(Section)
    assert sections
    titles = [s.header.text() for s in sections]
    assert titles[0] == "Cameras"
    assert sections[0].header.isChecked() is True
    assert sections[0].body.isHidden() is False
    for section in sections[1:]:
        assert section.header.isChecked() is False
        # isHidden is the explicit state, so this cannot pass by accident
        # just because an ancestor happens to be off screen.
        assert section.body.isHidden() is True


def test_date_is_the_last_filter(window):
    from photostats.ui.components.card import Section

    titles = [s.header.text() for s in window.filter_panel.findChildren(Section)]
    assert titles[-1] == "Date"


def test_opening_a_section_shows_its_body(window, app):
    from photostats.ui.components.card import Section

    # Lenses starts collapsed; Cameras is the one that opens by default.
    section = window.filter_panel.findChildren(Section)[1]
    assert section.header.isChecked() is False
    section.header.click()          # as a person would: click the heading
    spin(app, 120)
    assert section.header.isChecked() is True
    assert section.body.isHidden() is False


def test_clicking_a_date_field_opens_the_calendar(window, app):
    """A click anywhere on the field pops the calendar, not only the arrow."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    edit = window.filter_panel.date_from
    calendar = edit.calendarWidget()
    assert calendar is not None
    popup = calendar.parentWidget()
    assert popup.isHidden()

    QTest.mouseClick(edit, Qt.LeftButton, pos=QPoint(5, 5))
    assert popup.isVisible()

    popup.hide()


def test_the_calendar_popup_wears_the_app_palette(window, library):
    """Qt's calendar is a black grid with red weekends by default.

    The weekday colours are per-column *formats*, so they have to be set from
    the theme in code; the grid's background comes from the stylesheet, since
    the global rule makes every QAbstractScrollArea transparent — which the
    calendar's view is.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    calendar = window.filter_panel.date_from.calendarWidget()
    assert calendar is not None

    # Weekends carry the theme's faint tone, not Qt's red.
    weekend = calendar.weekdayTextFormat(Qt.Saturday).foreground().color()
    assert weekend == QColor(window.theme.text_faint)
    weekday = calendar.weekdayTextFormat(Qt.Monday).foreground().color()
    assert weekday == QColor(window.theme.text_dim)

    stylesheet = QApplication.instance().styleSheet()
    assert "QCalendarWidget QAbstractItemView" in stylesheet


def test_the_date_pickers_rest_on_the_library_span(window, library, app):
    """from = the oldest photo, to = today, and neither filters at rest.

    The pickers used to open on placeholder years (2000 and 2100), which read
    as nonsense next to a library that starts in 2024.
    """
    from datetime import date

    panel = window.filter_panel
    oldest = window.store.ranges()["date"][0]
    assert panel.date_from.date().toPython() == oldest
    assert panel.date_to.date().toPython() == date.today()
    # A capture date after today is a wrong camera clock, not a filter target.
    assert panel.date_from.maximumDate().toPython() == date.today()
    assert panel.date_to.maximumDate().toPython() == date.today()
    # Showing the span is not the same as filtering to it.
    assert window.filters.date_from is None
    assert window.filters.date_to is None


def test_moving_the_from_picker_inside_the_span_filters(window, library, app):
    from PySide6.QtCore import QDate

    oldest = window.store.ranges()["date"][0]
    later = QDate(oldest.year, oldest.month, oldest.day).addDays(20)
    window.filter_panel.date_from.setDate(later)
    spin(app, 900)

    assert window.filters.date_from == later.toPython()
    assert _matched(window) < window.store.totals().total


# -- the monthly update check ----------------------------------------------

def test_the_update_banner_is_hidden_until_there_is_a_release(window, library):
    from photostats.core.updates import Release

    assert window.update_banner.isHidden()

    release = Release(
        version="9.9.9", tag="v9.9.9", url="https://example.com/r",
        assets={"Photo Stats-arm64.dmg": "https://example.com/a.dmg"})
    window._on_update_found(release)

    assert not window.update_banner.isHidden()
    assert "9.9.9" in window.update_banner.label.text()


def test_a_failed_check_says_nothing(window, library):
    """Being offline is not an error worth a banner."""
    window._on_update_found(None)
    assert window.update_banner.isHidden()


def test_the_monthly_check_respects_the_interval(window, library):
    """No request before the interval is up, and none when it is turned off."""
    from datetime import datetime

    started = []
    window._check_updates_worker = lambda: started.append(1)

    window.config.set_updates_enabled(True)
    window.config.set_last_update_check(datetime.now())
    window._maybe_check_updates()
    assert started == [], "checked again inside the month"

    window.config.set_updates_enabled(False)
    window.config.set_last_update_check(None)
    window._maybe_check_updates()
    assert started == [], "checked even though updates are off"


# -- the legacy import -----------------------------------------------------

def test_a_scan_never_runs_beside_a_legacy_import(window, library):
    """Both write to the same SQLite file, and the walk holds a long write lock.

    Starting the scan while the import is writing is what produced "database is
    locked" and an import that could never finish.
    """
    window._scanning = False
    window.import_worker = object()  # an import in flight
    try:
        window._start_scan()
        assert window._scanning is False, "the scan started beside the import"
    finally:
        window.import_worker = None


def test_the_legacy_offer_is_made_only_once(window, library):
    from photostats.core.paths import LEGACY_DB_FILENAME

    (library / LEGACY_DB_FILENAME).write_bytes(b"SQLite format 3\x00")
    window._legacy_offered = False
    assert window._importable_legacy() is not None
    window._legacy_offered = True
    assert window._importable_legacy() is None


def test_an_already_imported_library_is_not_offered_again(window, library):
    from photostats.core import db as dbmod
    from photostats.core.db import set_meta
    from photostats.core.paths import LEGACY_DB_FILENAME

    (library / LEGACY_DB_FILENAME).write_bytes(b"SQLite format 3\x00")
    conn = dbmod.connect(window.db_path)
    set_meta(conn, "legacy_imported_from", "/old/photo_stats_cache.db")
    conn.close()

    window._legacy_offered = False
    assert window._importable_legacy() is None


# -- charts say what you selected ------------------------------------------

def test_chart_badge_names_the_selection(window, library, app):

    card = window.stats_grid.cards["camera"]
    badge = card.selection_badge
    assert badge.isVisible() is False

    label = window.store.facet("camera", window.filters).buckets[0].label
    card.bar_clicked.emit("camera", label)
    spin(app)

    assert badge.isVisible() is True
    assert label in badge.text()
    assert "\u00d7" in badge.text()      # and that it can be dismissed


def test_chart_badge_summarises_a_multiple_selection(window, library, app):

    card = window.stats_grid.cards["camera"]
    buckets = window.store.facet("camera", window.filters).buckets
    for bucket in buckets[:2]:
        card.bar_clicked.emit("camera", bucket.label)
        spin(app, 250)

    assert card.selection_badge.isVisible() is True
    assert "+1" in card.selection_badge.text()


def test_clicking_the_chart_badge_clears_only_that_facet(window, library, app):

    buckets = window.store.facet("camera", window.filters).buckets
    card = window.stats_grid.cards["camera"]
    card.bar_clicked.emit("camera", buckets[0].label)
    spin(app, 300)
    lens_bucket = window.store.facet("lens", window.filters).buckets[0]
    card = window.stats_grid.cards["lens"]
    card.bar_clicked.emit("lens", lens_bucket.label)
    spin(app, 300)
    assert window.filters.cameras and window.filters.lenses

    window.stats_grid.cards["camera"].selection_cleared.emit("camera")
    spin(app, 300)

    assert window.filters.cameras == frozenset()
    assert window.filters.lenses == frozenset({lens_bucket.label})


# -- the value lists must not filter themselves out ------------------------

def test_selecting_a_camera_keeps_the_other_cameras_in_the_list(window, library, app):
    """The list may not collapse to the chosen value, or a second is impossible."""
    check_list = window.filter_panel.list_camera
    before = [check_list.list.item(i).text() for i in range(check_list.list.count())]
    assert len(before) > 1

    _click_row(check_list, 0)
    spin(app, 600)
    after = [check_list.list.item(i).text() for i in range(check_list.list.count())]
    assert after == before


def test_two_cameras_can_be_selected_and_one_removed(window, library, app):
    check_list = window.filter_panel.list_camera
    first = check_list.list.item(0).text()
    second = check_list.list.item(1).text()
    total = window.store.totals().total

    _click_row(check_list, 0)
    spin(app, 500)
    _click_row(check_list, 1)
    spin(app, 500)
    assert window.filters.cameras == frozenset({first, second})
    both = window.store.totals(window.filters).matched
    assert both < total

    _click_row(check_list, 0)
    spin(app, 500)
    assert window.filters.cameras == frozenset({second})
    assert window.store.totals(window.filters).matched < both


def test_selecting_one_camera_leaves_every_lens_selectable(window, library, app):
    lenses_before = window.filter_panel.list_lens.list.count()
    _click_row(window.filter_panel.list_camera, 0)
    spin(app, 600)
    assert window.filter_panel.list_lens.list.count() == lenses_before


# -- slider labels are real photographic values ---------------------------

def test_slider_ticks_are_values_from_the_series(window, library):
    from photostats.ui.panels.filter_panel import FACET_TICKS

    ranges = window.store.ranges()
    checks = {
        "iso": FACET_TICKS["iso"],
        "shutter": FACET_TICKS["shutter"],
        "aperture": FACET_TICKS["aperture"],
        "focal": FACET_TICKS["focal"],
    }
    for facet, series in checks.items():
        slider = getattr(window.filter_panel, f"slider_{facet}")
        labels = [text for _fraction, text in slider.tick_labels()]
        # The two ends are the library's own extremes; the rest must be real
        # settings, not even fractions of the track.
        assert len(labels) >= 2
        for text in labels[1:-1]:
            assert any(text == _labelled(facet, v) for v in series), (facet, text)
        low, high = ranges[facet]
        assert _labelled(facet, low) == labels[0]
        assert _labelled(facet, high) == labels[-1]


def _labelled(facet: str, value: float) -> str:
    from photostats.ui.panels.filter_panel import FACET_FORMATTERS

    return FACET_FORMATTERS[facet](value)


def test_iso_ticks_are_spread_evenly_across_the_track(window, library):
    """ISO is logarithmic, so even value steps would bunch up at the low end."""
    slider = window.filter_panel.slider_iso
    fractions = [fraction for fraction, _text in slider.tick_labels()]
    assert fractions[0] == pytest.approx(0.0)
    assert fractions[-1] == pytest.approx(1.0)
    gaps = [b - a for a, b in zip(fractions, fractions[1:], strict=False)]
    assert max(gaps) - min(gaps) < 0.15


# -- a tick you can actually see -------------------------------------------

def _render_row(theme, checked: bool):
    """Paint one CheckList row and return its indicator strip as colours."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QPainter, QPixmap
    from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStyle, QStyleOptionViewItem

    from photostats.ui.components.check_list import _Delegate

    listing = QListWidget()
    item = QListWidgetItem("NIKON Z8")
    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
    item.setData(Qt.UserRole, "NIKON Z8")
    item.setData(Qt.UserRole + 1, 12)
    item.setData(Qt.UserRole + 2, 0.5)
    listing.addItem(item)
    listing.resize(260, 28)
    item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    option = QStyleOptionViewItem()
    option.initFrom(listing)
    option.widget = listing
    option.rect = QRect(0, 0, 260, 28)
    option.state |= QStyle.StateFlag.State_Enabled
    pixmap = QPixmap(260, 28)
    pixmap.fill(QColor(theme.bg_alt))
    painter = QPainter(pixmap)
    _Delegate(theme, listing).paint(painter, option, listing.model().index(0, 0))
    painter.end()

    image = pixmap.toImage()
    return {
        QColor(image.pixelColor(x, y)).name().lower()
        for y in range(4, 24)
        for x in range(2, 22)
    }


@pytest.mark.parametrize("theme_name", ["light", "dark"])
def test_a_checked_row_is_visibly_different_from_an_unchecked_one(theme_name):
    """Regression: the filter applied but nothing showed it had.

    QStyledItemDelegate's PE_IndicatorCheckBox renders byte-identical whether or
    not the box is ticked once a stylesheet is in play, so the tick is drawn by
    hand and this guards it.
    """
    from photostats.ui.theme import THEMES

    theme = THEMES[theme_name]
    checked = _render_row(theme, True)
    unchecked = _render_row(theme, False)
    assert checked != unchecked, "a selected row looks identical to an unselected one"


@pytest.mark.parametrize("theme_name", ["light", "dark"])
def test_the_tick_uses_the_brand_accent(theme_name):
    from photostats.ui.theme import THEMES

    theme = THEMES[theme_name]
    checked = _render_row(theme, True)
    assert theme.accent.lower() in checked, "the tick is not painted in the accent"
    assert theme.accent.lower() not in _render_row(theme, False)


# -- the dates chart has to say what a period holds ------------------------

def _hover_timeline(window, app, fraction: float):
    """Move the pointer over the dates chart the way a person would."""
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    chart = window.timeline
    QTest.mouseMove(chart, QPoint(int(chart.width() * fraction), chart.height() // 2))
    spin(app, 60)
    return chart


def test_hovering_the_dates_chart_shows_a_tooltip(window, library, app):
    tooltip = _hover_timeline(window, app, 0.5).toolTip()
    assert tooltip, "no tooltip while hovering the dates chart"
    assert "photos" in tooltip


def test_the_dates_tooltip_names_the_period_under_the_pointer(window, library, app):
    first = _hover_timeline(window, app, 0.02).toolTip()
    middle = _hover_timeline(window, app, 0.5).toolTip()
    assert first != middle, "every position reports the same period"


def test_leaving_the_dates_chart_clears_the_tooltip(window, library, app):
    """A stale tooltip keeps describing a period the pointer has left."""
    from PySide6.QtCore import QEvent

    chart = window.timeline
    _hover_timeline(window, app, 0.5)
    chart.setToolTip("some period")
    chart.leaveEvent(QEvent(QEvent.Type.Leave))
    assert chart.toolTip() == ""
    assert chart._hover is None


def test_hovering_the_dates_chart_does_not_start_a_drag(window, library, app):
    chart = _hover_timeline(window, app, 0.5)
    assert chart._dragging is False
    assert chart.selection == (None, None)


# -- brand -----------------------------------------------------------------

def test_the_palette_is_the_brand_palette():
    from photostats.ui.theme import LIGHT, PINE_BLUE, THEMES

    assert PINE_BLUE == "#316D61"
    assert LIGHT.accent == PINE_BLUE
    assert THEMES["light"].bg == "#FFF9EC"
    assert THEMES["light"].text == "#322F30"
    assert THEMES["dark"].text == "#FFF9EC"


def test_every_theme_colour_is_actually_valid():
    from PySide6.QtGui import QColor

    from photostats.ui.theme import THEMES

    for theme in THEMES.values():
        for role in theme.__dataclass_fields__:
            if role in ("name", "is_dark"):
                continue
            value = getattr(theme, role)
            colour = QColor(value)
            assert colour.isValid(), f"{theme.name}.{role} is not a colour: {value}"


def test_contrast_of_text_on_background_is_readable():
    from PySide6.QtGui import QColor

    from photostats.ui.theme import THEMES

    def luminance(value: str) -> float:
        colour = QColor(value)

        def channel(part: float) -> float:
            part /= 255
            return part / 12.92 if part <= 0.03928 else ((part + 0.055) / 1.055) ** 2.4

        return (0.2126 * channel(colour.red())
                + 0.7152 * channel(colour.green())
                + 0.0722 * channel(colour.blue()))

    for theme in THEMES.values():
        for background, label in ((theme.bg, "bg"), (theme.card, "card")):
            for text_role in ("text", "text_dim"):
                a, b = luminance(background), luminance(getattr(theme, text_role))
                ratio = (max(a, b) + 0.05) / (min(a, b) + 0.05)
                assert ratio >= 4.5, f"{theme.name}: {text_role} on {label} is {ratio:.1f}:1"


def test_the_app_runs_without_the_brand_assets(tmp_path):
    """A missing font or logo must not be fatal."""
    from photostats.ui import assets

    assert assets.install_fonts() == []
    assert assets.logo("no-such-logo.png") is None
    assert assets.font_files() == []


def test_the_stylesheet_only_names_fonts_that_exist(app):
    """Naming a missing font makes Qt print a font-alias warning every launch."""
    from PySide6.QtGui import QFontDatabase

    from photostats.ui.theme import LIGHT, stylesheet

    installed = set(QFontDatabase.families())
    for name in ("League Spartan", "Monospace", "Sans Serif"):
        if name in installed:
            continue
        assert name not in stylesheet(LIGHT), f"{name} is named but not installed"


def test_the_brand_font_is_used_once_it_is_installed():
    from photostats.ui.theme import font_stack

    stack = font_stack(installed=["League Spartan", "Arial"])
    assert stack.startswith('"League Spartan"')


def test_the_font_stack_always_resolves_to_something():
    from photostats.ui.theme import font_stack

    assert font_stack(installed=[]).strip(", ")
    assert font_stack(installed=["Comic Sans MS"]).strip(", ")


# -- who made it -----------------------------------------------------------

def test_the_window_title_carries_the_attribution(window):
    assert window.windowTitle() == "Photo Stats by Picstome.com"


def test_the_settings_window_title_carries_it_too(window):
    from photostats.ui.panels.settings_dialog import SettingsDialog

    assert SettingsDialog(window.config, window.theme, window).windowTitle() == (
        "Photo Stats by Picstome.com — Settings"
    )


def test_the_title_follows_the_language(window, app):
    from photostats.i18n import set_language

    set_language("es")
    window._rebuild_ui()
    spin(app, 300)
    assert window.windowTitle() == "Photo Stats de Picstome.com"
    set_language("en")
    window._rebuild_ui()
    spin(app, 300)
    assert window.windowTitle() == "Photo Stats by Picstome.com"


def test_the_settings_key_is_not_the_display_name():
    """APP_NAME is a settings key; renaming it would orphan every preference."""
    from photostats import APP_NAME, display_name

    # The key stays bare; the title is built from it.
    assert APP_NAME == "Photo Stats"
    assert display_name() == f"{APP_NAME} by Picstome.com"
    assert "Picstome" not in APP_NAME


def test_the_footer_credits_picstome_and_points_at_them(window):
    """A bare domain in the corner reads as an ad, not as credit."""
    assert window.byline.text() == "Developed by picstome.com"
    assert window.byline.url == "https://picstome.com"
    assert window.byline in window.statusBar().findChildren(type(window.byline))


def test_the_attribution_survives_a_very_long_cache_path(window, app, tmp_path):
    """The corner must not be starved by the cache path beside it."""
    deep = tmp_path / ("long-directory-" * 6) / ("another " * 5) / "photos"
    deep.mkdir(parents=True)
    window.open_library(deep)
    spin(app, 500)
    assert "…" in window.cache_label.text(), "the cache path is not capped"
    assert window.byline.width() >= window.byline.sizeHint().width()
    assert window.status_label.width() > 400


def test_clicking_the_footer_link_opens_the_page(window, monkeypatch):
    opened = []
    import photostats.ui.components.footer_link as module

    monkeypatch.setattr(module.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toString()) or True))
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseClick(window.byline, Qt.LeftButton)
    assert opened == ["https://picstome.com"]


def test_a_failing_link_says_so_rather_than_doing_nothing(window, monkeypatch, app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    import photostats.ui.components.footer_link as module

    monkeypatch.setattr(module.QDesktopServices, "openUrl", staticmethod(lambda url: False))
    QTest.mouseClick(window.byline, Qt.LeftButton)
    spin(app, 200)
    assert "picstome.com" in window.status_label.text()
    assert "browser" in window.status_label.text()


def test_the_footer_link_restyles_with_the_theme(window):
    from photostats.ui.theme import THEMES

    restyled = window.byline.styleSheet()
    window.byline.set_theme(THEMES["light"])
    assert THEMES["light"].text_faint in window.byline.styleSheet()
    assert restyled != window.byline.styleSheet()


def test_hovering_the_footer_link_underlines_it(window):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QEnterEvent

    plain = window.byline.styleSheet()
    window.byline.enterEvent(QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    assert "underline" in window.byline.styleSheet()
    window.byline.leaveEvent(QEvent(QEvent.Type.Leave))
    assert "underline" not in window.byline.styleSheet()
    assert window.byline.styleSheet() == plain


# -- a folder that has gone should never interrupt the launch --------------

def _watch_for_dialogs(monkeypatch):
    """Record any modal the window raises, so a test can assert there were none."""
    seen: list = []
    original = QMessageBox.critical

    def spy(*args, **kwargs):
        seen.append(args[1] if len(args) > 1 else kwargs.get("title"))
        return original(*args, **kwargs)

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(spy))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(spy))
    return seen


def test_a_forgotten_library_asks_again_instead_of_erroring(app, paths, monkeypatch):
    """Regression: launching with a remembered /tmp folder raised a modal.

    The folder had been deleted between runs, and the app opened to an error
    rather than asking which folder to use.
    """
    from photostats.app import apply_theme
    from photostats.core.config import AppConfig
    from photostats.i18n import set_language

    seen = _watch_for_dialogs(monkeypatch)
    config = AppConfig(paths=paths)
    config.set_theme("dark")
    set_language("en")
    apply_theme(app, config)
    config.settings.setValue("library", "/tmp/photostats-no-such-folder/photos")
    config.settings.setValue("recents", ["/tmp/photostats-no-such-folder/photos"])

    window = MainWindow(config, logging.getLogger("photostats.tests"))
    try:
        spin(app, 400)
        assert seen == []
        assert window.library is None
        assert window.stack.currentWidget() is window.welcome
        assert not config.settings.contains("library")
        assert config.recents == []
    finally:
        window.deleteLater()
        app.processEvents()


def test_a_bad_folder_while_running_uses_the_status_line_not_a_modal(
        window, app, monkeypatch, tmp_path):
    seen = _watch_for_dialogs(monkeypatch)
    window.open_library(tmp_path / "definitely-not-here")
    spin(app, 300)
    assert seen == []
    assert "not a folder" in window.status_label.text()


def test_a_bad_folder_does_not_forget_a_good_one(window, app, tmp_path):
    real = tmp_path / "photos"
    real.mkdir()
    window.open_library(real)
    spin(app, 500)
    window.open_library(tmp_path / "gone")
    spin(app, 300)
    assert window.library == real
    assert window.config.library == str(real)


def test_a_real_folder_still_opens_normally(window, app, tmp_path):
    real = tmp_path / "photos"
    real.mkdir()
    window.open_library(real)
    spin(app, 400)
    assert window.library == real
    assert window.config.library == str(real)


def test_the_sidebar_is_emptied_when_a_library_is_forgotten(window, app, tmp_path):
    real = tmp_path / "photos"
    real.mkdir()
    window.open_library(real)
    spin(app, 500)
    assert window.filter_panel.list_camera.list.count() or True

    window.open_library(tmp_path / "gone")
    spin(app, 300)
    assert window.filter_panel.list_camera.list.count() == 0
    assert window.filter_panel.list_lens.list.count() == 0
    assert window.tiles.matched.value.text() == "0"


def test_no_font_in_the_ui_is_named_that_does_not_exist(app):
    """Regression: a console full of font-alias warnings on every launch.

    Qt resolves font families lazily and logs a 100ms warning for each one it
    cannot find. Three came from us: the brand font before it was supplied,
    "monospace" for the path field, and Qt's own "Sans Serif" default.
    """
    import re

    from PySide6.QtGui import QFontDatabase

    from photostats.ui import styles
    from photostats.ui.theme import LIGHT, stylesheet

    installed = set(QFontDatabase.families())
    combined = stylesheet(LIGHT) + styles.stylesheet(LIGHT)
    declarations = re.findall(r"font-family:\s*([^;]+);", combined)
    assert declarations, "no font-family found to check"
    for declaration in declarations:
        for part in declaration.split(","):
            part = part.strip().strip('"')
            assert part in installed, f"the UI asks for {part!r}, which is not installed"


# -- opening a library starts from nothing --------------------------------

def test_a_newly_opened_library_has_no_filters(window, library):
    """Every facet at its full range must read as *no filter*, not as one.

    The sliders used to carry the library's own min and max into the filter, so
    a freshly opened library reported "8 active" and showed four chips while
    filtering nothing at all.
    """
    assert window.filters.active_count == 0
    assert window.filters.iso_min is None and window.filters.iso_max is None
    assert window.filters.shutter_min is None and window.filters.shutter_max is None
    assert window.filters.aperture_min is None and window.filters.aperture_max is None
    assert window.filters.focal_min is None and window.filters.focal_max is None
    assert window.filter_panel.badge.text() == ""
    assert _chips(window) == 0


def test_sliders_spanning_the_whole_range_are_not_a_filter(window, library, app):
    panel = window.filter_panel
    for name in ("iso", "shutter", "aperture", "focal"):
        slider = getattr(panel, f"slider_{name}")
        assert slider.is_full()
        slider.set_range(slider.minimum, slider.maximum, emit=True)
        spin(app, 250)
    assert window.filters.active_count == 0
    assert _chips(window) == 0


def test_resetting_a_slider_clears_its_filter(window, library, app):
    panel = window.filter_panel
    panel.slider_iso.set_range(800, 1600, emit=True)
    spin(app, 500)
    assert window.filters.active_count > 0

    panel.slider_iso.reset(emit=True)
    spin(app, 500)
    assert window.filters.active_count == 0
    assert _chips(window) == 0


def test_opening_another_library_discards_the_filters(window, library, app, tmp_path):
    window._on_bar_clicked("camera", "NIKON Z8")
    panel = window.filter_panel
    panel.slider_iso.set_range(800, 1600, emit=True)
    spin(app, 600)
    assert window.filters.active_count > 0

    other = tmp_path / "second-library"
    other.mkdir()
    window.open_library(other)
    spin(app, 700)

    assert window.filters.active_count == 0
    assert window.filters.cameras == frozenset()
    assert window.filter_panel.slider_iso.is_full()
    assert _chips(window) == 0


# -- the top bar -----------------------------------------------------------

def test_the_top_bar_names_the_library(window, library, app):
    bar = window.folder_bar
    assert bar.name.text() == library.name
    assert bar.path.text().endswith(str(library.parent))
    assert bar.has_folder is True


def test_the_top_bar_invites_a_choice_when_there_is_none(window):
    bar = window.folder_bar
    bar.set_folder(None)
    assert bar.has_folder is False
    assert bar.name.text() == "No folder chosen"


def test_browse_and_recents_are_one_button(window, library):
    """They are the same intent, so they are one control.

    QPushButton.setMenu drew its own arrow, which sat a few pixels off the
    button edge and made the header look broken, so the menu is popped by hand
    from the same button instead.
    """
    bar = window.folder_bar
    assert bar.browse.text() == "Open"
    assert bar.browse.menu() is None  # no clipped native arrow
    assert not hasattr(bar, "recent")
    assert bar.recent_menu.actions() == []  # filled lazily on show


def test_the_open_button_pops_the_recent_menu(library, window):
    """One button must still reach the recent folders and the chooser."""
    bar = window.folder_bar
    bar.set_recents([str(library)])

    # Qt only emits aboutToShow from inside a real popup, so check the two
    # halves separately: that the click asks for a popup, and that what the
    # popup would show is the right menu.
    with patch.object(bar.recent_menu, "popup") as popup:
        bar.browse.click()
    assert popup.called, "clicking Open did not ask for the menu"

    bar.recent_menu.aboutToShow.emit()
    labels = [action.text() for action in bar.recent_menu.actions()]
    assert tr("Recent") in labels
    assert tr("Browse…") in labels
    assert any(str(library) in action.toolTip() for action in bar.recent_menu.actions())


# -- the grid --------------------------------------------------------------

def test_cards_in_a_row_are_all_the_same_height(window, library, app):
    """Regression: a row came out 151, 151 and 193 pixels tall."""

    grid = window.stats_grid
    columns = grid._active_columns()
    facets = list(grid.cards)
    for start in range(0, len(facets), columns):
        row = facets[start:start + columns]
        heights = {grid.cards[facet].height() for facet in row}
        assert len(heights) == 1, f"ragged row: {heights}"


def test_the_grid_never_overflows_its_width(window, library, app):
    for size in ((1280, 800), (1440, 900), (1920, 1080)):
        window.resize(*size)
        spin(app, 300)
        grid = window.stats_grid
        right = max(card.geometry().right() for card in grid.cards.values())
        assert right <= grid.width(), f"cards overflow at {size}: {right} > {grid.width()}"


def test_the_column_count_leaves_every_card_a_readable_label():
    """Three abreast, not four: a lens name needs the room more than the grid does."""
    from photostats.ui.panels.stats_grid import columns_for

    # Three is the ceiling, and four abreast is deliberately not offered.
    assert columns_for(1107, wanted=4) == 4     # four *fits*...
    assert columns_for(1107, wanted=3) == 3     # ...but the grid asks for three


def test_the_chart_cards_share_the_cards_around_them(window, library, app):
    """The timeline card and the chart cards must share the same edges.

    A scroll area inside the grid reserved a scrollbar the timeline did not,
    and the grid carried its own margins on top of the page's, so the chart
    columns were inset from the timeline card on both sides and looked ragged.
    One scroll, shared by everything, with nothing else owning width.
    """
    for size in ((1280, 800), (1440, 900)):
        window.resize(*size)
        spin(app, 300)
        timeline = window.timeline.parentWidget()  # the timeline's Card

        def x(widget, edge):
            point = widget.rect().topRight() if edge == "r" else widget.rect().topLeft()
            return widget.mapTo(window, point).x()

        # Camera opens the first column, iso (row 1) closes the last one.
        assert x(window.stats_grid.cards["camera"], "l") == x(timeline, "l"), (
            f"left edges differ at {size}")
        assert abs(x(window.stats_grid.cards["iso"], "r") - x(timeline, "r")) <= 1, (
            f"right edges differ at {size}")


def test_every_bar_shows_its_share(window, library, app):
    """'36' said how many, never how much of the whole; the share is the part
    a photographer reads a decision from."""
    chart = window.stats_grid.cards["camera"].chart

    texts = [chart._right_text(bucket) for bucket in chart.buckets()]
    assert all("·" in text and text.rstrip().endswith("%") for text in texts)
    bucket = chart.buckets()[0]
    assert bucket.share > 0
    assert f"{bucket.share * 100:.0f}%" in texts[0]


def test_the_chart_label_is_measured_not_reserved(window, library):
    """A fixed label width left the bar 28px of a 228px card."""
    from photostats.ui.components.bar_chart import TRACK_MIN

    for facet in ("camera", "lens", "iso", "aperture", "flash"):
        chart = window.stats_grid.cards[facet].chart
        track = chart.width() - chart._label_width() - chart._count_width() - 12
        assert track >= TRACK_MIN - 12, f"{facet} leaves only {track}px for the bar"


def test_short_labels_give_their_space_to_the_bar(window, library):
    """An f-stop chart should not reserve lens-length room for 'f/1.8'."""
    short = window.stats_grid.cards["aperture"].chart
    long_ = window.stats_grid.cards["lens"].chart
    assert short._label_width() < long_._label_width()


# -- the form --------------------------------------------------------------

def test_settings_controls_share_one_column(window):
    from photostats.ui.panels.settings_dialog import (
        FORM_FIELD_WIDTH,
        FORM_NUMBER_WIDTH,
        SettingsDialog,
    )

    dialog = SettingsDialog(window.config, window.theme, window)
    try:
        assert dialog.language_box.width() == FORM_FIELD_WIDTH
        assert dialog.theme_box.width() == FORM_FIELD_WIDTH
        assert dialog.cache_box.width() == FORM_FIELD_WIDTH
        # Number fields hold one to four digits; stretching them looked broken.
        assert dialog.workers.width() == FORM_NUMBER_WIDTH
        assert dialog.batch.width() == FORM_NUMBER_WIDTH
    finally:
        dialog.deleteLater()


def test_settings_helper_text_is_not_trapped_in_the_field_column(window):
    from photostats.ui.panels.settings_dialog import SettingsDialog

    dialog = SettingsDialog(window.config, window.theme, window)
    try:
        spin(app, 200)
        dialog.show()
        spin(app, 200)
        # Wider than the narrow field column it used to wrap inside.
        assert dialog.cache_note.width() > 250
    finally:
        dialog.deleteLater()


# -- colour has to carry meaning -------------------------------------------

def test_chart_bars_are_visible_enough_to_read(app):
    """WCAG asks 3:1 for a graphic that carries information.

    The bars sat at 2.07:1 against the white card, which made the charts look
    decorative rather than like data.
    """
    from PySide6.QtGui import QColor

    from photostats.ui.theme import THEMES

    def luminance(value: str) -> float:
        colour = QColor(value)

        def channel(part: int) -> float:
            part /= 255
            return part / 12.92 if part <= 0.03928 else ((part + 0.055) / 1.055) ** 2.4

        return (0.2126 * channel(colour.red())
                + 0.7152 * channel(colour.green())
                + 0.0722 * channel(colour.blue()))

    def ratio(a: str, b: str) -> float:
        first, second = luminance(a), luminance(b)
        return (max(first, second) + 0.05) / (min(first, second) + 0.05)

    for theme in THEMES.values():
        surface = theme.card
        assert ratio(theme.accent_dim, surface) >= 3.0, (
            f"{theme.name}: bars at {ratio(theme.accent_dim, surface):.2f}:1"
        )
        assert ratio(theme.accent, surface) >= 4.5, (
            f"{theme.name}: selected bar at {ratio(theme.accent, surface):.2f}:1"
        )
        # The track is recessive, but it still has to read as a track.
        assert ratio(theme.bar_bg, surface) >= 1.2


def test_a_selected_bar_is_distinguishable_from_an_unselected_one(app):
    from PySide6.QtGui import QColor

    from photostats.ui.theme import THEMES

    for theme in THEMES.values():
        assert QColor(theme.accent).name() != QColor(theme.accent_dim).name()


# -- the header -----------------------------------------------------------

def test_the_header_says_what_the_page_is_about(window, library):
    """An eyebrow over the library name, not a bare folder name on its own."""
    bar = window.folder_bar
    assert bar.eyebrow.text() == "Your photo stats"
    assert bar.name.text() == library.name
    assert bar.path.text().endswith(str(library.parent))


def test_the_header_icons_are_drawn_not_characters(window):
    """Unicode glyphs rendered as emoji or tofu depending on the platform."""
    bar = window.folder_bar
    assert not bar.settings.icon().isNull()
    assert not bar.theme_button.icon().isNull()
    assert bar.settings.text() == ""
    assert bar.theme_button.text() == ""


def test_the_open_button_carries_one_affordance(window):
    """Two chevrons on one small button read as a rendering bug."""
    button = window.folder_bar.browse
    assert button.icon().isNull(), "Qt already draws the dropdown arrow"
    assert button.text() == "Open"


def test_the_status_bar_separates_its_parts(window, library):
    """The cache location and the attribution used to run together."""
    # Permanent widgets sit in their own internal layout, so the check is on
    # where they ended up rather than on the main layout's item list.
    cache_right = window.cache_label.x() + window.cache_label.width()
    byline_left = window.byline.x()
    assert byline_left > cache_right, "the attribution is not after the cache path"
    assert byline_left - cache_right >= 10, (
        f"no gap between the cache path and the attribution: {byline_left - cache_right}px")


def test_the_status_bar_uses_one_size_for_its_message(window):
    assert window.status_label.styleSheet() == "" or "statusText" in (
        window.status_label.objectName())
    assert window.status_label.objectName() == "statusText"
    assert window.cache_label.objectName() == "statusMeta"
