"""Insights must never quote a share outside 0–100%.

Every sentence divides a facet's counts by the selection's total, so a facet
computed *without* its own filter (the chart's cross-filtered view) would
report a library-wide count against a selection-sized denominator — the
"4058% of these are from …" bug after picking a camera.
"""

from __future__ import annotations

import re

import pytest
from conftest import make_library

from photostats.core import db as dbmod
from photostats.core.filters import FLASH_FIRED, Filter
from photostats.core.indexer import Indexer
from photostats.core.insights import Insights
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


def _percentages(text: str) -> list[int]:
    return [int(value) for value in re.findall(r"(\d+)%", text)]


FILTERED_STATES = [
    Filter(cameras=frozenset({"NIKON Z8"})),
    Filter(cameras=frozenset({"Canon EOS R6"})),
    Filter(iso_min=200, iso_max=800),
    Filter(aperture_min=1.8, aperture_max=2.8),
    Filter(flash=FLASH_FIRED),
    Filter(lenses=frozenset({"FE 35mm F1.4 GM"})),
]


@pytest.mark.parametrize("filters", FILTERED_STATES, ids=lambda f: f"filters={f}")
def test_no_insight_reports_a_share_above_100(store, filters):
    for insight in Insights(store, filters).build():
        for percentage in _percentages(insight.text):
            assert 0 <= percentage <= 100, (
                f"{percentage}% in {insight.text!r} for {filters}"
            )


def test_the_camera_insight_stops_speaking_when_the_camera_filter_speaks(store):
    """Its buckets ignore the camera filter, so "of these" would be a lie."""
    keys = [i.key for i in Insights(store, Filter(cameras=frozenset({"NIKON Z8"}))).build()]
    assert "insight.camera_dominates" not in keys


def test_the_lens_insight_stops_speaking_when_the_lens_filter_speaks(store):
    filters = Filter(lenses=frozenset({"FE 35mm F1.4 GM"}))
    keys = [i.key for i in Insights(store, filters).build()]
    assert "insight.use_lens" not in keys


def test_unfiltered_insights_still_report_their_shares(store):
    """The guard must not silence the normal case."""
    built = Insights(store, Filter()).build()
    keys = [i.key for i in built]
    assert "insight.camera_dominates" in keys
    for insight in built:
        for percentage in _percentages(insight.text):
            assert 0 <= percentage <= 100, insight.text
