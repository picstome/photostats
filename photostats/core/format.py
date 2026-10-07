"""Formatting helpers shared by the UI, the exporters and the CLI."""

from __future__ import annotations

from .parse import format_fnumber, format_focal, format_shutter

#: Column order used by every export and by the results table header.
RESULT_FIELDS = (
    "filename",
    "folder",
    "date",
    "camera",
    "lens",
    "iso",
    "shutter",
    "aperture",
    "focal",
    "focal_35mm",
    "flash",
    "white_balance",
    "file_type",
    "width",
    "height",
    "megapixels",
    "path",
)

FLASH_LABELS = {1: "Yes", 0: "No", None: "Unknown"}
TYPE_LABELS = {"raw": "RAW", "jpeg": "JPEG", "tiff": "TIFF/HEIC", "other": "Other"}
WB_LABELS = {
    "auto": "Auto", "manual": "Manual", "daylight": "Daylight", "cloudy": "Cloudy",
    "fluorescent": "Fluorescent", "tungsten": "Tungsten", "shade": "Shade",
    "flash": "Flash", "unknown": "Unknown",
}


def row_to_dict(row) -> dict:
    """Flatten a photos row into export-friendly, pre-formatted strings."""
    rel_path = row["rel_path"]
    folder, _, filename = rel_path.rpartition("/")
    return {
        "filename": filename,
        "folder": folder,
        "date": row["taken_at"] or "",
        "camera": row["camera"] or "",
        "lens": row["lens"] or "",
        "iso": row["iso"] if row["iso"] is not None else "",
        "shutter": format_shutter(row["shutter_seconds"]),
        "aperture": format_fnumber(row["fnumber"]),
        "focal": format_focal(row["focal_mm"]),
        "focal_35mm": format_focal(row["focal35_mm"]),
        "flash": FLASH_LABELS.get(row["flash_fired"], "Unknown"),
        "white_balance": WB_LABELS.get(row["white_balance"], row["white_balance"] or ""),
        "file_type": TYPE_LABELS.get(row["file_type"], row["file_type"] or ""),
        "width": row["width"] or "",
        "height": row["height"] or "",
        "megapixels": row["megapixels"] or "",
        "path": rel_path,
    }


def facet_label(value, formatter=None) -> str:
    if formatter:
        return formatter(value)
    return str(value)
