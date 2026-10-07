"""The filter model and its translation into SQL.

Kept deliberately free of Qt and SQLite so that every clause can be unit-tested
in isolation: ``to_sql`` is the single place that decides what "filtered" means.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

#: Facet keys used by the UI. They double as the ``omit`` arguments of to_sql.
FACET_CAMERA = "camera"
FACET_LENS = "lens"
FACET_ISO = "iso"
FACET_SHUTTER = "shutter"
FACET_APERTURE = "aperture"
FACET_FOCAL = "focal"
FACET_FLASH = "flash"
FACET_WHITE_BALANCE = "white_balance"
FACET_FILE_TYPE = "file_type"
FACET_YEAR = "year"
FACET_MONTH = "month"
FACET_RESOLUTION = "resolution"

FLASH_ANY = "any"
FLASH_FIRED = "fired"
FLASH_NOT_FIRED = "not_fired"


@dataclass(frozen=True)
class Filter:
    """An immutable description of what the user is looking at."""

    date_from: date | None = None
    date_to: date | None = None
    include_no_date: bool = False
    cameras: frozenset[str] = frozenset()
    lenses: frozenset[str] = frozenset()
    white_balance: frozenset[str] = frozenset()
    file_types: frozenset[str] = frozenset()
    resolutions: frozenset[str] = frozenset()
    iso_min: float | None = None
    iso_max: float | None = None
    shutter_min: float | None = None
    shutter_max: float | None = None
    aperture_min: float | None = None
    aperture_max: float | None = None
    focal_min: float | None = None
    focal_max: float | None = None
    flash: str = FLASH_ANY
    search: str = ""

    # -- construction helpers ---------------------------------------------
    def toggled(self, facet: str, value: str) -> Filter:
        """Add or remove one value of a multi-select facet."""
        attribute = self._attribute(facet)
        updated = set(getattr(self, attribute))
        if value in updated:
            updated.discard(value)
        else:
            updated.add(value)
        return replace(self, **{attribute: frozenset(updated)})

    def without(self, facet: str) -> Filter:
        """Same filter with one facet cleared (used by the chip row)."""
        return replace(self, **{self._attribute(facet): Filter()._values(facet)})

    @staticmethod
    def _attribute(facet: str) -> str:
        """Filter field that backs a facet: 'camera' -> 'cameras'."""
        if facet in FACET_COLUMNS:
            return FACET_COLUMNS[facet][0]
        if facet == FACET_RESOLUTION:
            return "resolutions"
        raise KeyError(f"{facet} is not a multi-select facet")

    @staticmethod
    def _values(facet: str):
        if facet == FACET_RESOLUTION:
            return frozenset()
        return frozenset()

    @property
    def is_empty(self) -> bool:
        return self == Filter()

    @property
    def active_count(self) -> int:
        """Number of individual constraints, for the 'filters (n)' badge."""
        total = 0
        for facet in (FACET_CAMERA, FACET_LENS, FACET_WHITE_BALANCE, FACET_FILE_TYPE,
                      FACET_RESOLUTION):
            total += len(getattr(self, self._attribute(facet)))
        for low, high in (
            ("iso_min", "iso_max"), ("shutter_min", "shutter_max"),
            ("aperture_min", "aperture_max"), ("focal_min", "focal_max"),
        ):
            total += int(getattr(self, low) is not None) + int(getattr(self, high) is not None)
        total += int(self.date_from is not None) + int(self.date_to is not None)
        total += int(self.flash != FLASH_ANY)
        total += int(bool(self.search.strip()))
        return total

    def facet_active(self, facet: str) -> bool:
        """True when this facet carries a constraint of its own.

        The mirror of :meth:`to_sql`'s ``omit``: when True, ``store.facet``
        computed its buckets *without* this facet's clause, so their counts
        describe the library ignoring that filter rather than the current
        selection. A camera filter with 26 selected photos against a
        1,055-photo facet gave "4058% of these are from …", because the facet
        and the total were never the same scope. Callers ask here before
        quoting a facet's count against ``totals.matched``. The equivalence
        with ``to_sql`` is asserted in ``tests/test_filters.py``, so a new
        clause cannot drift away from it.
        """
        if facet == FACET_ISO:
            return self.iso_min is not None or self.iso_max is not None
        if facet == FACET_SHUTTER:
            return self.shutter_min is not None or self.shutter_max is not None
        if facet == FACET_APERTURE:
            return self.aperture_min is not None or self.aperture_max is not None
        if facet == FACET_FOCAL:
            return self.focal_min is not None or self.focal_max is not None
        if facet == FACET_FLASH:
            return self.flash != FLASH_ANY
        if facet == FACET_RESOLUTION:
            return bool(self.resolutions)
        if facet in FACET_COLUMNS:
            return bool(getattr(self, FACET_COLUMNS[facet][0]))
        # Facets with no clause of their own (month, year, …) are never
        # cross-filtered: to_sql ignores the omit for them, so their buckets
        # always describe the whole selection.
        return False

    # -- SQL ---------------------------------------------------------------
    def to_sql(self, omit: str | None = None) -> tuple[str, list]:
        """Return (where_clause, params); omit a facet to ignore its own filter.

        Omitting a facet's clause is what makes the charts cross-filtering: the
        counts shown for one attribute are computed with every *other* filter
        applied, so you can see what selecting a value would yield.
        """
        clauses: list[str] = []
        params: list = []

        if omit != "date":
            if self.date_from is not None:
                clauses.append("taken_at >= ?")
                params.append(f"{self.date_from.isoformat()} 00:00:00")
            if self.date_to is not None:
                clauses.append("taken_at <= ?")
                params.append(f"{self.date_to.isoformat()} 23:59:59")
            if not self.include_no_date:
                # Photos without an EXIF date fall back to the file date; the UI
                # can opt them back in with one checkbox.
                clauses.append("date_source != 'none'")

        for facet, (attribute, column) in FACET_COLUMNS.items():
            values = getattr(self, attribute)
            if omit == facet or not values:
                continue
            keys = _keys_for(facet, values)
            if not keys:
                continue
            placeholders = ",".join("?" * len(keys))
            clauses.append(f"{column} IN ({placeholders})")
            params.extend(keys)

        if omit != FACET_RESOLUTION and self.resolutions:
            keys = _keys_for("resolution", self.resolutions)
            if keys:
                placeholders = ",".join("?" * len(keys))
                clauses.append(f"resolution IN ({placeholders})")
                params.extend(keys)

        for facet, column, low, high in (
            (FACET_ISO, "iso", "iso_min", "iso_max"),
            (FACET_SHUTTER, "shutter_seconds", "shutter_min", "shutter_max"),
            (FACET_APERTURE, "fnumber", "aperture_min", "aperture_max"),
            (FACET_FOCAL, "focal_mm", "focal_min", "focal_max"),
        ):
            if omit == facet:
                continue
            minimum, maximum = getattr(self, low), getattr(self, high)
            if minimum is not None:
                clauses.append(f"{column} >= ?")
                params.append(minimum)
            if maximum is not None:
                clauses.append(f"{column} <= ?")
                params.append(maximum)

        if omit != FACET_FLASH and self.flash != FLASH_ANY:
            if self.flash == FLASH_FIRED:
                clauses.append("flash_fired = 1")
            elif self.flash == FLASH_NOT_FIRED:
                clauses.append("flash_fired = 0")

        if self.search.strip():
            needle = f"%{self.search.strip().lower()}%"
            clauses.append("(lower(rel_path) LIKE ? OR lower(coalesce(camera, '')) LIKE ?)")
            params.extend([needle, needle])

        return (" AND ".join(clauses) if clauses else "1=1"), params


#: facet -> (Filter attribute, database column). Keys are compared, not labels,
#: so that "NIKON Z8" and "nikon z8" are the same selection.
FACET_COLUMNS = {
    FACET_CAMERA: ("cameras", "camera_key"),
    FACET_LENS: ("lenses", "lens_key"),
    FACET_WHITE_BALANCE: ("white_balance", "white_balance"),
    FACET_FILE_TYPE: ("file_types", "file_type"),
}


def _keys_for(facet: str, values: frozenset[str]) -> list[str]:
    """Translate displayed values into the keys stored in the database."""
    from .parse import normalize_key

    keys = []
    for value in values:
        if facet in (FACET_CAMERA, FACET_LENS):
            key = normalize_key(value)
        elif facet == FACET_RESOLUTION:
            key = value.replace("×", "x").replace(" ", "").lower()
        else:
            key = value.lower()
        if key:
            keys.append(key)
    return keys


EMPTY = Filter()


@dataclass(frozen=True)
class FilterPreset:
    """A named, ready-made filter shown as a chip in the UI."""

    key: str
    label: str
    value: Filter = field(default=EMPTY)
