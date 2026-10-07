"""Read-side queries: totals, cross-filtered facets, timeline, results, insights.

Every aggregation is a single indexed ``GROUP BY`` over ``photos``. Facets are
computed with their own filter clause omitted, which is what lets the charts show
what selecting a value *would* yield.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .filters import FACET_APERTURE, FACET_CAMERA, FACET_FOCAL, FACET_ISO, Filter
from .parse import format_fnumber, format_focal, format_shutter

#: Catalogue keys, not literals: month names are translated at display time.
MONTH_NAMES = ("month.jan", "month.feb", "month.mar", "month.apr", "month.may",
               "month.jun", "month.jul", "month.aug", "month.sep", "month.oct",
               "month.nov", "month.dec")

#: A facet shown as a bar chart: display column, grouping key, label formatter.
#:
#: Grouping uses the normalised *key* so that "NIKON Z8" and "nikon  z8" are one
#: bar, which is also what the filters match on. Grouping on the indexed key
#: instead of the display text lets SQLite use the index.
FACETS: dict[str, tuple[str, str, callable | None]] = {
    FACET_CAMERA: ("camera", "camera_key", None),
    "lens": ("lens", "lens_key", None),
    FACET_ISO: ("iso", "iso", str),
    FACET_APERTURE: ("fnumber", "fnumber", format_fnumber),
    "shutter": ("shutter_seconds", "shutter_seconds", format_shutter),
    FACET_FOCAL: ("focal_mm", "focal_mm", format_focal),
    "flash": ("flash_fired", "flash_fired", lambda v: {1: "Fired", 0: "Not fired"}.get(v, "Unknown")),
    "white_balance": ("white_balance", "white_balance", None),
    "file_type": ("file_type", "file_type", None),
    "month": ("month", "month", lambda m: month_label(int(m)) if m else "?"),
    "year": ("year", "year", str),
    "resolution": ("resolution", "resolution", None),
}

#: Charts whose x axis is numeric and therefore binned when very fine-grained.
BINNED_FACETS = {FACET_ISO, FACET_APERTURE, "shutter", FACET_FOCAL}


@dataclass
class Bucket:
    """One bar of a chart."""

    key: object
    label: str
    count: int
    #: Share of the facet's own total, 0.0–1.0. Filled in by PhotoStore.facet.
    share: float = 0.0


@dataclass
class FacetResult:
    """One attribute chart.

    ``total`` is the number of photos passing the other filters (the facet's own
    filter omitted), so it matches ``PhotoStore.totals`` for the same selection.
    ``unknown`` is the subset with no value for this attribute; it is excluded
    from the bars, and therefore from the shares.
    """

    facet: str
    title: str
    buckets: list[Bucket]
    total: int
    unknown: int = 0
    kind: str = "list"

    @property
    def is_empty(self) -> bool:
        return not self.buckets

    @property
    def counted(self) -> int:
        """Photos that actually carry a value for this attribute."""
        return sum(bucket.count for bucket in self.buckets)


@dataclass
class Timeline:
    """Bucketed counts over time, at day, week, month or year granularity."""

    granularity: str
    label: str
    points: list[tuple[date, int]]


@dataclass
class Totals:
    matched: int = 0
    total: int = 0
    without_date: int = 0
    unreadable: int = 0

    @property
    def share(self) -> float:
        return (self.matched / self.total * 100) if self.total else 0.0


FACET_TITLES = {
    FACET_CAMERA: "Cameras",
    "lens": "Lenses",
    FACET_ISO: "ISO",
    FACET_APERTURE: "Aperture",
    "shutter": "Shutter speed",
    FACET_FOCAL: "Focal length",
    "flash": "Flash",
    "white_balance": "White balance",
    "file_type": "File type",
    "month": "Month",
    "year": "Year",
    "resolution": "Resolution",
}


class PhotoStore:
    """Read-only access to an indexed library.

    SQLite connections belong to the thread that opened them, so the UI must not
    share one store between its thread and the query worker. Use
    :meth:`forked` to get an equivalent store for another thread.
    """

    def __init__(self, db_path, readonly: bool = True) -> None:
        self.db_path = db_path
        self.readonly = readonly
        #: One connection per thread: SQLite binds a connection to the thread
        #: that opened it, and two threads must never share or invalidate one.
        self._connections: dict[int, sqlite3.Connection] = {}
        self._lock = threading.Lock()
        #: (total photos, photos without an EXIF date) — filter independent.
        self._unfiltered: tuple[int, int] | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """The connection belonging to the calling thread, opened on first use."""
        from .db import connect

        thread = threading.get_ident()
        with self._lock:
            conn = self._connections.get(thread)
            if conn is None:
                conn = connect(self.db_path, readonly=self.readonly)
                self._connections[thread] = conn
            return conn

    def forked(self) -> PhotoStore:
        """An equivalent store for use on another thread."""
        return PhotoStore(self.db_path, readonly=self.readonly)

    def close(self) -> None:
        with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()
        for conn in connections:
            with contextlib.suppress(sqlite3.Error):
                conn.close()

    def __enter__(self) -> PhotoStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- basics ------------------------------------------------------------
    def totals(self, filters: Filter = Filter()) -> Totals:
        """Counts for the current filter.

        The library total and the no-EXIF-date count do not depend on the filter,
        so they are computed once and reused: they were two full scans per refresh.
        """
        where, params = filters.to_sql()
        matched = self.conn.execute(
            f"SELECT COUNT(*) FROM photos WHERE {where}", params
        ).fetchone()[0]
        cached = self._unfiltered
        if cached is None:
            total = self.conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
            without_date = self.conn.execute(
                "SELECT COUNT(*) FROM photos WHERE date_source != 'exif'"
            ).fetchone()[0]
            cached = self._unfiltered = (int(total), int(without_date))
        return Totals(matched=int(matched), total=cached[0], without_date=cached[1])

    def invalidate_cache(self) -> None:
        """Drop the cached unfiltered counts (call after a scan or import)."""
        self._unfiltered = None

    def facet(self, name: str, filters: Filter = Filter(), limit: int | None = None,
              *, omit_self: bool = True) -> FacetResult:
        """Counts for one facet, with every *other* filter applied.

        Omitting this facet's own clause is what powers cross-filtering: the
        chart keeps showing every camera so you can see what picking another
        one would yield. Those counts describe the library, not the selection —
        anything that reports the selection (a tile, an export) must pass
        ``omit_self=False`` to keep the two scopes apart.
        """
        if name not in FACETS:
            raise ValueError(f"unknown facet {name!r}")
        column, key_column, formatter = FACETS[name]
        where, params = filters.to_sql(omit=name if omit_self else None)
        # Always select both a key (what filters match) and a label (what the
        # user reads). When they differ the label is the most common spelling.
        select = (
            f"{column} AS k, {column} AS label"
            if key_column == column
            else f"{key_column} AS k, MAX({column}) AS label"
        )
        sql = (
            f"SELECT {select}, COUNT(*) AS c FROM photos WHERE {where} "
            f"GROUP BY k ORDER BY c DESC, k ASC"
        )
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self.conn.execute(sql, params).fetchall()

        buckets: list[Bucket] = []
        unknown = 0
        for row in rows:
            key = row["k"]
            if key is None:
                unknown += row["c"]
                continue
            label = row["label"] or key
            buckets.append(
                Bucket(key=key, label=_format_bucket(name, label, formatter), count=row["c"])
            )
        counted = sum(bucket.count for bucket in buckets)
        for bucket in buckets:
            bucket.share = (bucket.count / counted) if counted else 0.0
        return FacetResult(
            facet=name,
            title=FACET_TITLES.get(name, name.title()),  # translated at display time
            buckets=buckets,
            total=counted + unknown,
            unknown=unknown,
            kind="range" if name in BINNED_FACETS else "list",
        )

    def facets(self, names, filters: Filter = Filter()) -> dict[str, FacetResult]:
        return {name: self.facet(name, filters) for name in names}

    # -- timeline ----------------------------------------------------------
    def timeline(self, filters: Filter = Filter()) -> Timeline:
        where, params = filters.to_sql()
        rows = self.conn.execute(
            f"SELECT year, month, day, COUNT(*) AS c FROM photos WHERE {where} "
            f"GROUP BY year, month, day",
            params,
        ).fetchall()
        if not rows:
            return Timeline(granularity="month", label="No photos", points=[])

        days = [
            (date(int(row["year"]), int(row["month"]), int(row["day"])), row["c"])
            for row in rows
            if row["year"] and row["month"] and row["day"]
        ]
        if not days:
            return Timeline(granularity="month", label="No photos", points=[])
        days.sort()
        first, last = days[0][0], days[-1][0]
        span = (last - first).days

        if span <= 45:
            granularity = "day"
            points = days
            label = "Per day"
        elif span <= 400:
            granularity = "week"
            points = _group_by(days, lambda d: d - timedelta(days=d.weekday()))
            label = "Per week"
        elif span <= 4000:
            granularity = "month"
            points = _group_by(days, lambda d: date(d.year, d.month, 1))
            label = "Per month"
        else:
            granularity = "year"
            points = _group_by(days, lambda d: date(d.year, 1, 1))
            label = "Per year"
        return Timeline(granularity=granularity, label=label, points=points)

    # -- results -----------------------------------------------------------
    RESULT_COLUMNS = (
        "rel_path, taken_at, camera, lens, iso, shutter_seconds, fnumber, focal_mm, "
        "focal35_mm, flash_fired, white_balance, file_type, width, height, megapixels"
    )

    def results(
        self,
        filters: Filter = Filter(),
        sort: str = "date_desc",
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[sqlite3.Row], int]:
        where, params = filters.to_sql()
        order = _sort_clause(sort)
        # Two statements rather than COUNT(*) OVER (): SQLite materialises the
        # whole window before applying LIMIT, which measured 5x slower here.
        total = self.conn.execute(
            f"SELECT COUNT(*) FROM photos WHERE {where}", params
        ).fetchone()[0]
        rows = self.conn.execute(
            f"SELECT {self.RESULT_COLUMNS} FROM photos WHERE {where} {order} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return rows, int(total)

    def all_results(self, filters: Filter = Filter(), sort: str = "date_desc"):
        """Yield every matching row (used by the exporters)."""
        where, params = filters.to_sql()
        order = _sort_clause(sort)
        cursor = self.conn.execute(
            f"SELECT {self.RESULT_COLUMNS} FROM photos WHERE {where} {order}", params
        )
        while True:
            chunk = cursor.fetchmany(2000)
            if not chunk:
                return
            yield from chunk

    def photo(self, rel_path: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM photos WHERE rel_path = ?", (rel_path,)
        ).fetchone()

    #: Column shown -> the normalised key that filters actually match on.
    DISTINCT_KEYS = {
        "camera": "camera_key",
        "lens": "lens_key",
    }

    #: Columns distinct() is allowed to group by. Anything else is rejected
    #: rather than interpolated into SQL.
    ALLOWED_DISTINCT_COLUMNS = frozenset({
        "camera", "camera_key", "lens", "lens_key", "white_balance", "file_type",
        "iso", "fnumber", "shutter_seconds", "focal_mm", "flash_fired", "resolution",
        "year", "month", "rel_path",
    })

    def distinct(
        self, column: str, filters: Filter = Filter(), omit: str | None = None
    ) -> list[tuple[str, int]]:
        """Every observed value with its count, for the sidebar filter lists.

        Grouping uses the same key as :meth:`facet`, so the list and the chart
        always agree on which photos each value represents.

        ``omit`` is the facet this list belongs to, and that facet's own filter
        is left out. Without it, picking one camera would reduce the camera list
        to that single camera, and there would be no way to pick a second one or
        to change your mind.
        """
        if column not in self.ALLOWED_DISTINCT_COLUMNS:
            raise ValueError(f"distinct() does not support column {column!r}")
        where, params = filters.to_sql(omit=omit)
        key = self.DISTINCT_KEYS.get(column)
        if key:
            rows = self.conn.execute(
                f"SELECT MAX({column}) AS label, COUNT(*) AS n FROM photos "
                f"WHERE {where} AND {key} IS NOT NULL GROUP BY {key} ORDER BY n DESC",
                params,
            )
            return [(row["label"] or "", row["n"]) for row in rows]
        return [
            (row[0], row[1])
            for row in self.conn.execute(
                f"SELECT {column}, COUNT(*) FROM photos WHERE {where} AND {column} IS NOT NULL "
                f"GROUP BY {column} ORDER BY COUNT(*) DESC",
                params,
            )
        ]

    def ranges(self) -> dict[str, tuple | None]:
        """Observed min/max per numeric column, to seed the range sliders.

        Also the library's date span, so the date pickers can rest on the
        oldest day in the library and on today rather than on placeholder
        years like 2000 and 2100.
        """
        row = self.conn.execute(
            "SELECT MIN(iso), MAX(iso), MIN(shutter_seconds), MAX(shutter_seconds), "
            "MIN(fnumber), MAX(fnumber), MIN(focal_mm), MAX(focal_mm), "
            "MIN(taken_at), MAX(taken_at) FROM photos"
        ).fetchone()
        return {
            "iso": (row[0], row[1]),
            "shutter": (row[2], row[3]),
            "aperture": (row[4], row[5]),
            "focal": (row[6], row[7]),
            # ISO-8601 text sorts lexicographically, so MIN/MAX are the ends.
            "date": (_day(row[8]), _day(row[9])),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _day(value) -> date | None:
    """The calendar day of an ISO timestamp, or None when there is no date."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _format_bucket(facet: str, key, formatter) -> str:
    if facet == "flash":
        return {1: "Fired", 0: "Not fired"}.get(key, "Unknown")
    if facet == "file_type":
        return {"raw": "RAW", "jpeg": "JPEG", "tiff": "TIFF / HEIC"}.get(key, str(key))
    if facet == "resolution":
        try:
            width, height = (int(part) for part in str(key).split("x"))
        except ValueError:
            return str(key)
        return f"{width}×{height}"
    if formatter:
        return formatter(key)
    return str(key)


def _group_by(days, key) -> list[tuple[date, int]]:
    totals: dict[date, int] = {}
    for day, count in days:
        bucket = key(day)
        totals[bucket] = totals.get(bucket, 0) + count
    return sorted(totals.items())


def _sort_clause(sort: str) -> str:
    return {
        "date_desc": "ORDER BY taken_at DESC, rel_path DESC",
        "date_asc": "ORDER BY taken_at ASC, rel_path ASC",
        "camera": "ORDER BY camera_key, taken_at DESC",
        "lens": "ORDER BY lens_key, taken_at DESC",
        "iso_desc": "ORDER BY iso DESC, taken_at DESC",
        "iso_asc": "ORDER BY iso ASC, taken_at DESC",
        "shutter": "ORDER BY shutter_seconds, taken_at DESC",
        "aperture": "ORDER BY fnumber, taken_at DESC",
        "focal": "ORDER BY focal_mm, taken_at DESC",
        "name": "ORDER BY rel_path",
    }.get(sort, "ORDER BY taken_at DESC, rel_path DESC")


def format_datetime(value: str | None) -> str:
    if not value:
        return "—"
    try:
        moment = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value
    return moment.strftime("%Y-%m-%d %H:%M")


def month_label(value: int | None) -> str:
    """'Mar' or 'marzo' — the month name in the active language."""
    from ..i18n import tr

    if not value or not 1 <= value <= 12:
        return "?"
    return tr(MONTH_NAMES[value - 1])
