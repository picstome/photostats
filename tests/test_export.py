"""Exports describe the selection, never the chart's cross-filtered view.

A report headed "24 photos" must not then list the library's cameras beneath
it: with a camera filter set, ``store.facet`` without ``omit_self=False``
counts every body anyway, because that is what the chart needs in order to
offer the alternatives.
"""

from __future__ import annotations

import pytest
from conftest import make_library

from photostats.core import db as dbmod
from photostats.core import export
from photostats.core.filters import Filter
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


NIKON = Filter(cameras=frozenset({"NIKON Z8"}))


def test_stats_dict_lists_only_the_selected_cameras(store):
    stats = export.stats_dict(store, NIKON)
    assert set(stats["camera"]) == {"NIKON Z8"}
    assert sum(v["count"] for v in stats["camera"].values()) == store.totals(NIKON).matched


def test_stats_dict_shares_of_a_filtered_selection_stay_within_100(store):
    for facet, values in export.stats_dict(store, NIKON).items():
        for label, figures in values.items():
            assert 0 <= figures["share"] <= 100, (facet, label, figures)


def test_text_report_keeps_the_selections_cameras_only(store):
    report = export.to_text(store, NIKON)
    assert "NIKON Z8" in report
    assert "Canon EOS R6" not in report
    assert f"{store.totals(NIKON).matched:,} photos" in report


def test_unfiltered_report_is_unchanged_by_scoping(store):
    """With nothing selected the two scopes are the same query."""
    unfiltered = Filter()
    cross = store.facet("camera", unfiltered)
    scoped = store.facet("camera", unfiltered, omit_self=False)
    assert [b.count for b in cross.buckets] == [b.count for b in scoped.buckets]
