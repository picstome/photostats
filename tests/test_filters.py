"""facet_active must mirror to_sql's omit, or a share could exceed 100%.

The insights divide facet counts by ``totals.matched``. That is only sound
while the facet was computed with *all* filters applied — exactly the
condition ``to_sql(omit=facet)`` breaks. ``facet_active`` claims to answer
"would omitting this facet change the WHERE clause?", so the tests assert
the claim against ``to_sql`` itself rather than restating the mapping.
"""

from __future__ import annotations

from photostats.core.filters import (
    FACET_APERTURE,
    FACET_CAMERA,
    FACET_FLASH,
    FACET_FOCAL,
    FACET_ISO,
    FACET_LENS,
    FACET_SHUTTER,
    FLASH_FIRED,
    Filter,
)
from photostats.core.queries import FACETS


def every_constraint() -> Filter:
    """A filter that constrains every facet to_sql knows how to omit."""
    return Filter(
        cameras=frozenset({"NIKON Z8"}),
        lenses=frozenset({"NIKKOR Z 24-70mm f/2.8 S"}),
        white_balance=frozenset({"auto"}),
        file_types=frozenset({"raw"}),
        resolutions=frozenset({"large"}),
        iso_min=100,
        iso_max=3200,
        shutter_min=1 / 1000,
        shutter_max=1 / 30,
        aperture_min=1.4,
        aperture_max=8.0,
        focal_min=24,
        focal_max=200,
        flash=FLASH_FIRED,
    )


def test_no_facet_is_active_on_an_empty_filter():
    for name in FACETS:
        assert not Filter().facet_active(name), name


def test_a_constrained_facet_reports_itself_active():
    filters = every_constraint()
    for name in (
        FACET_CAMERA, FACET_LENS, FACET_ISO, FACET_SHUTTER, FACET_APERTURE,
        FACET_FOCAL, FACET_FLASH, "white_balance", "file_type", "resolution",
    ):
        assert filters.facet_active(name), name


def test_facet_active_mirrors_to_sql_omit_for_every_facet():
    """The load-bearing equivalence: ask to_sql, not the mapping.

    If a new clause is added to to_sql without a matching branch here — or a
    branch appears that to_sql does not honour — this fails, which is what
    keeps "4058% of these are from …" from coming back.
    """
    for filters in (Filter(), every_constraint()):
        for name in FACETS:
            full = filters.to_sql(omit=None)[0]
            omitted = filters.to_sql(omit=name)[0]
            assert filters.facet_active(name) == (full != omitted), (
                f"facet_active({name!r}) disagrees with to_sql for {filters}"
            )


def test_month_and_year_are_never_active():
    """Omitting them changes nothing, so their buckets always describe the
    selection — the busiest-month insight needs no guard of its own."""
    filters = every_constraint()
    for name in ("month", "year"):
        assert not filters.facet_active(name)
        assert filters.to_sql(omit=name) == filters.to_sql(omit=None)
