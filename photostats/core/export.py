"""Export the current selection: CSV, JSON and a shareable text summary."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator

from .filters import Filter
from .format import RESULT_FIELDS, row_to_dict
from .queries import FACETS, PhotoStore

EXPORT_SORT = "date_desc"


def iter_rows(store: PhotoStore, filters: Filter = Filter()) -> Iterator[dict]:
    """Every matching photo as a flat dict, in a stable order."""
    for row in store.all_results(filters, EXPORT_SORT):
        yield row_to_dict(row)


def to_csv(store: PhotoStore, filters: Filter = Filter()) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=RESULT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for record in iter_rows(store, filters):
        writer.writerow(record)
    return buffer.getvalue()


def to_json(store: PhotoStore, filters: Filter = Filter()) -> str:
    payload = {
        "generated_by": "Photo Stats",
        "filters": describe_filters(filters),
        "summary": summary_dict(store, filters),
        "stats": stats_dict(store, filters),
        "photos": list(iter_rows(store, filters)),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def summary_dict(store: PhotoStore, filters: Filter = Filter()) -> dict:
    totals = store.totals(filters)
    return {
        "matched": totals.matched,
        "total_in_library": totals.total,
        "percent_of_library": round(totals.share, 2),
        "photos_without_exif_date": totals.without_date,
    }


def stats_dict(store: PhotoStore, filters: Filter = Filter()) -> dict:
    """Per-facet counts and shares *of the selection*.

    Cross-filtered buckets (the chart's view, with each facet's own filter
    omitted) would export the library instead: with a camera selected, the
    camera section would list every body at library counts under a report
    headed by the selection's total. Exports have no chart to feed, so the
    facets are scoped: ``omit_self=False``.
    """
    out: dict[str, dict] = {}
    for name in FACETS:
        result = store.facet(name, filters, omit_self=False)
        if result.is_empty:
            continue
        out[name] = {
            bucket.label: {"count": bucket.count, "share": round(bucket.share * 100, 2)}
            for bucket in result.buckets
        }
    return out


def to_text(store: PhotoStore, filters: Filter = Filter(), threshold: int = 3) -> str:
    """The classic console report, in markdown, for pasting anywhere."""
    totals = store.totals(filters)
    lines = [
        "Photo Stats",
        "=" * 40,
        f"{totals.matched:,} photos"
        + (f" of {totals.total:,} in the library" if totals.matched != totals.total else ""),
    ]
    if not filters.is_empty:
        lines.append(f"Filters: {describe_filters(filters, human=True)}")
    lines.append("")

    for name in ("year", "month", FACET_CAMERA_KEY, FACET_LENS_KEY, "iso", "shutter",
                 "aperture", "focal", "flash", "white_balance", "resolution", "file_type"):
        # Scoped to the selection, as stats_dict is: a report headed "21,404
        # photos" must not then list the library's cameras beneath it.
        result = store.facet(name, filters, omit_self=False)
        if result.is_empty:
            continue
        lines.append(f"=== {result.title} ===")
        shown = [b for b in result.buckets if b.count >= threshold]
        for bucket in shown:
            lines.append(f"{bucket.label}: {bucket.count:,} ({bucket.share * 100:.1f}%)")
        other = sum(b.count for b in result.buckets if b.count < threshold)
        if other:
            lines.append(f"Other (<{threshold}): {other:,}")
        if result.unknown:
            lines.append(f"No data: {result.unknown:,}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


FACET_CAMERA_KEY = "camera"
FACET_LENS_KEY = "lens"


def describe_filters(filters: Filter, human: bool = False) -> dict | str:
    """Machine-readable filter description, or a readable one for reports."""
    parts: dict = {}
    if filters.date_from or filters.date_to:
        parts["date"] = f"{filters.date_from or '…'} → {filters.date_to or '…'}"
    for name, label in (
        ("cameras", "camera"), ("lenses", "lens"), ("white_balance", "WB"),
        ("file_types", "type"), ("resolutions", "resolution"),
    ):
        values = getattr(filters, name)
        if values:
            parts[label] = sorted(values)
    for name, label in (
        ("iso", "ISO"), ("shutter", "shutter"), ("aperture", "aperture"), ("focal", "focal"),
    ):
        low, high = getattr(filters, f"{name}_min"), getattr(filters, f"{name}_max")
        if low is not None or high is not None:
            parts[label] = f"{low if low is not None else '…'}–{high if high is not None else '…'}"
    if filters.flash != "any":
        parts["flash"] = filters.flash
    if filters.search.strip():
        parts["search"] = filters.search
    if not human:
        return parts
    if not parts:
        return "none"
    return " · ".join(
        f"{key}: {', '.join(str(item) for item in value) if isinstance(value, list) else value}"
        for key, value in parts.items()
    )
