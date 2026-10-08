"""Tests for the filter model and the cross-filtered facet queries."""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest
from conftest import make_library

from photostats.core import db as dbmod
from photostats.core.filters import (
    FACET_CAMERA,
    FACET_ISO,
    Filter,
)
from photostats.core.indexer import Indexer
from photostats.core.queries import PhotoStore


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "photos"
    make_library(root, count=40)
    db = root / "photo_stats.db"
    dbmod.init_db(db)
    Indexer(db, root).run()
    with PhotoStore(db) as store:
        yield store


# -- to_sql --------------------------------------------------------------
def test_empty_filter_matches_everything():
    where, params = Filter().to_sql()
    assert where
    assert params == [] or params


def test_camera_filter_lowercases_into_a_key():
    where, params = Filter(cameras=frozenset({"NIKON Z8"})).to_sql()
    assert "camera_key IN (?)" in where
    assert params == ["nikon z8"]


def test_multiple_cameras_produce_multiple_placeholders():
    where, params = Filter(cameras=frozenset({"NIKON Z8", "Canon EOS R6"})).to_sql()
    assert "camera_key IN (?,?)" in where
    assert sorted(params) == ["canon eos r6", "nikon z8"]


def test_range_filters_use_inclusive_bounds():
    where, params = Filter(iso_min=200, iso_max=800).to_sql()
    assert "iso >= ?" in where and "iso <= ?" in where
    assert tuple(params) == (200, 800)


def test_open_ended_range_emits_one_clause():
    where, params = Filter(iso_min=200).to_sql()
    assert "iso >= ?" in where and "iso <= ?" not in where


def test_date_range_covers_whole_days():
    where, params = Filter(date_from=date(2024, 5, 1), date_to=date(2024, 5, 31)).to_sql()
    assert "taken_at >= ?" in where and "taken_at <= ?" in where
    assert params[0] == "2024-05-01 00:00:00"
    assert params[1] == "2024-05-31 23:59:59"


def test_photos_without_a_date_are_excluded_by_default():
    where, _ = Filter().to_sql()
    assert "date_source != 'none'" in where
    where, _ = Filter(include_no_date=True).to_sql()
    assert "date_source != 'none'" not in where


def test_omit_removes_only_that_facet():
    filters = Filter(cameras=frozenset({"NIKON Z8"}), iso_min=200)
    full, _ = filters.to_sql()
    without_camera, _ = filters.to_sql(omit=FACET_CAMERA)
    without_iso, _ = filters.to_sql(omit=FACET_ISO)
    assert "camera_key" in full and "iso >= ?" in full
    assert "camera_key" not in without_camera and "iso >= ?" in without_camera
    assert "camera_key" in without_iso and "iso >= ?" not in without_iso


def test_flash_filter():
    assert "flash_fired = 1" in Filter(flash="fired").to_sql()[0]
    assert "flash_fired = 0" in Filter(flash="not_fired").to_sql()[0]
    assert "flash_fired" not in Filter(flash="any").to_sql()[0]


def test_search_uses_a_lower_bound_like_match():
    where, params = Filter(search="beach").to_sql()
    assert where.count("lower(") == 2
    assert params == ["%beach%", "%beach%"]


def test_toggle_adds_then_removes():
    filters = Filter()
    once = filters.toggled(FACET_CAMERA, "NIKON Z8")
    assert once.cameras == frozenset({"NIKON Z8"})
    assert once.toggled(FACET_CAMERA, "NIKON Z8") == filters


def test_without_clears_one_facet():
    filters = Filter(cameras=frozenset({"NIKON Z8"}), iso_min=100)
    assert filters.without(FACET_CAMERA).cameras == frozenset()
    assert filters.without(FACET_CAMERA).iso_min == 100


def test_active_count_and_is_empty():
    assert Filter().is_empty
    assert Filter().active_count == 0
    filters = Filter(cameras=frozenset({"A", "B"}), iso_min=100, flash="fired")
    assert not filters.is_empty
    assert filters.active_count == 4


def test_filter_is_immutable():
    """Filters are values, not boxes: the UI replaces instead of mutating."""
    filters = Filter()
    with pytest.raises(dataclasses.FrozenInstanceError):
        filters.iso_min = 100  # type: ignore[misc]


# -- queries -------------------------------------------------------------
def test_totals_without_filters(store):
    totals = store.totals()
    assert totals.matched == totals.total == 40
    assert totals.share == 100.0


def test_totals_respect_filters(store):
    totals = store.totals(Filter(cameras=frozenset({"NIKON Z8"})))
    assert 0 < totals.matched < totals.total


def test_facet_total_excludes_its_own_filter(store):
    """A chart is sized by the *other* filters, so it can still offer alternatives."""
    filters = Filter(cameras=frozenset({"NIKON Z8"}), iso_min=800)
    chart = store.facet(FACET_CAMERA, filters)
    assert chart.total == store.totals(Filter(iso_min=800)).matched
    assert chart.total > store.totals(filters).matched


def test_cross_filtered_facet_ignores_only_its_own_filter(store):
    filters = Filter(cameras=frozenset({"NIKON Z8"}))
    result = store.facet(FACET_CAMERA, filters)
    # The camera chart still offers the other cameras, so you can switch to them.
    assert len(result.buckets) > 1
    nikon = next(b for b in result.buckets if b.label == "NIKON Z8")
    assert nikon.count == store.totals(filters).matched


def test_cross_filtered_facet_applies_other_filters(store):
    """A facet is computed with the *other* filters applied but not its own."""
    filters = Filter(cameras=frozenset({"NIKON Z8"}), iso_min=800)
    iso_chart = store.facet(FACET_ISO, filters)
    # The ISO filter is omitted, so low ISO values are still offered…
    assert min(bucket.key for bucket in iso_chart.buckets) < 800
    # …but the camera and date filters still narrow the chart down.
    assert iso_chart.total == store.totals(Filter(cameras=frozenset({"NIKON Z8"}))).matched
    nikon_only = store.facet(FACET_ISO, Filter(cameras=frozenset({"NIKON Z8"})))
    assert nikon_only.total < store.facet(FACET_ISO, Filter()).total


def test_shares_are_relative_to_the_values_present(store):
    result = store.facet(FACET_CAMERA)
    assert sum(b.share for b in result.buckets) == pytest.approx(1.0)
    assert result.counted == sum(b.count for b in result.buckets)


def test_omit_self_scopes_a_facet_to_the_selection(store):
    """Cross-filtering is for charts; a report about "the selection" is not.

    With a camera picked, ``omit_self=False`` keeps the camera clause, so the
    buckets and their total describe exactly the matched photos.
    """
    filters = Filter(cameras=frozenset({"NIKON Z8"}))
    cross = store.facet(FACET_CAMERA, filters)
    scoped = store.facet(FACET_CAMERA, filters, omit_self=False)
    assert len(cross.buckets) > 1          # the chart keeps offering alternatives
    assert [b.label for b in scoped.buckets] == ["NIKON Z8"]
    assert scoped.total == store.totals(filters).matched
    assert sum(b.count for b in scoped.buckets) == store.totals(filters).matched


def test_month_facet_uses_month_names(store):
    result = store.facet("month")
    assert {b.label for b in result.buckets} <= {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"}


def test_flash_facet_has_readable_labels(store):
    result = store.facet("flash")
    assert {b.label for b in result.buckets} <= {"Fired", "Not fired"}


def test_range_facet_formats_labels(store):
    assert store.facet("aperture").buckets[0].label.startswith("f/")
    assert store.facet("shutter").buckets[0].label.startswith(("1/", "0."))
    assert store.facet("focal").buckets[0].label.endswith("mm")


def test_facet_kind_marks_the_sliders(store):
    assert store.facet(FACET_ISO).kind == "range"
    assert store.facet(FACET_CAMERA).kind == "list"


def test_timeline_picks_a_granularity(store):
    timeline = store.timeline()
    assert timeline.granularity in ("day", "week", "month", "year")
    assert timeline.points
    assert sum(count for _day, count in timeline.points) == 40


def test_timeline_follows_the_date_filter(store):
    narrowed = store.timeline(Filter(date_from=date(2024, 5, 1), date_to=date(2024, 5, 31)))
    assert sum(count for _day, count in narrowed.points) < 40


def test_results_are_paged_and_sorted(store):
    filters = Filter(cameras=frozenset({"NIKON Z8"}))
    rows, total = store.results(filters, limit=5)
    assert total == store.totals(filters).matched
    assert len(rows) == 5
    dates = [row["taken_at"] for row in rows]
    assert dates == sorted(dates, reverse=True)


def test_all_results_streams_everything(store):
    filters = Filter(cameras=frozenset({"NIKON Z8"}))
    rows = list(store.all_results(filters))
    assert len(rows) == store.totals(filters).matched


def test_ranges_seed_the_sliders(store):
    ranges = store.ranges()
    assert ranges["iso"][0] < ranges["iso"][1]
    assert ranges["focal"][0] < ranges["focal"][1]


def test_ranges_ignore_a_zero_focal_and_fnumber(store):
    """A camera that wrote 0 for a value it did not know must not set the track.

    One 0 focal length turned the focal slider into a 0-1600 log track whose
    handle read "3.6e-06mm"; the same for f-number.
    """
    from photostats.core import db as dbmod

    conn = dbmod.connect(store.db_path)
    conn.execute("INSERT INTO photos (rel_path, focal_mm, fnumber) VALUES ('zero.jpg', 0, 0)")
    conn.commit()
    conn.close()

    ranges = store.ranges()
    assert ranges["focal"][0] >= 1
    assert ranges["aperture"][0] >= 0.5


def test_ranges_include_the_library_date_span(store):
    """The date pickers need the oldest day in the library, as a real date."""
    oldest, newest = store.ranges()["date"]
    assert isinstance(oldest, date) and isinstance(newest, date)
    assert oldest == date(2024, 5, 1)
    assert oldest <= newest


def test_distinct_values_are_ordered_by_frequency(store):
    values = store.distinct("camera_key")
    assert values
    assert values[0][1] >= values[-1][1]
