"""Turn raw exiftool output (or a legacy cache row) into normalised columns.

Everything here is pure and defensive: photos come from hundreds of camera
models, so a missing or oddly-typed tag must never raise. The same functions are
used for freshly extracted metadata and for the rows migrated from the original
console script's database.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from typing import Any

from .formats import file_type_of

DATE_SOURCE_EXIF = "exif"
DATE_SOURCE_MTIME = "mtime"
DATE_SOURCE_NONE = "none"

#: exiftool tags requested, in one call. The ``#`` suffix suppresses print
#: conversion for numeric tags while leaving Flash/WhiteBalance human readable.
EXIFTAGS = [
    "DateTimeOriginal#",
    "SubSecTimeOriginal",
    "CreateDate#",
    "Model",
    "LensModel",
    "Lens",
    "LensID",
    "LensType",
    "LensMake",
    "LensSerialNumber",
    "ISO#",
    "ExposureTime#",
    "FNumber#",
    "ApertureValue#",
    "FocalLength#",
    "FocalLengthIn35mmFormat#",
    "Flash",
    "WhiteBalance",
    "ImageWidth#",
    "ImageHeight#",
    "FileType",
    "MIMEType",
    "OffsetTimeOriginal",
]

_EXIFTOOL_ARGS = [
    *[f"-{tag}" for tag in EXIFTAGS],
    "-api",
    "largefilesupport=1",
    "-charset",
    "filename=UTF8",
]

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_FRACTION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)$")
_WS_RE = re.compile(r"\s+")
_UNKNOWN_RE = re.compile(r"^unknown\s*\((\d+)\)$", re.I)
_KELVIN_RE = re.compile(r"^([\d.]+)\s*k$", re.I)

# WhiteBalance per the EXIF 2.3 specification. exiftool only decodes 0 and 1
# itself, so the remaining values reach us either as a bare integer or wrapped in
# "Unknown (N)"; mapping them here beats throwing the information away.
_WB_EXIF_VALUES = {
    0: "auto",
    1: "manual",
    2: "daylight",
    3: "fluorescent",
    4: "tungsten",
    5: "flash",
    6: "cloudy",
    7: "shade",
}

#: Canon/Nikon style spellings mapped onto a small stable vocabulary.
WB_MAPPING = {
    "auto": "auto",
    "auto (ambience priority)": "auto",
    "auto (white priority)": "auto",
    "daylight": "daylight",
    "cloudy": "cloudy",
    "overcast": "cloudy",
    "fluorescent": "fluorescent",
    "tungsten": "tungsten",
    "incandescent": "tungsten",
    "shade": "shade",
    "flash": "flash",
    "manual": "manual",
    "custom": "manual",
    "manual temperature (kelvin)": "manual",
    "kelvin": "manual",
}


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------
def to_float(value: Any) -> float | None:
    """Best-effort float from numbers and strings like '35.0 mm', '1/125', '0x1d'."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else None
    if isinstance(value, (list, tuple, dict, set)):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text[:2].lower() == "0x":
        try:
            return float(int(text, 16))
        except ValueError:
            return None
    fraction = _FRACTION_RE.match(text)
    if fraction:
        num, den = float(fraction.group(1)), float(fraction.group(2))
        return num / den if den else None
    match = _NUM_RE.search(text)
    if not match:
        return None
    try:
        result = float(match.group(0))
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def to_int(value: Any) -> int | None:
    number = to_float(value)
    return int(round(number)) if number is not None else None


def parse_iso(value: Any) -> int | None:
    """Lowest ISO from a scalar or a bracketed burst such as ``[100, 800]``."""
    if isinstance(value, (list, tuple)):
        values = [to_int(item) for item in value]
        values = [item for item in values if item and item > 0]
        return min(values) if values else None
    if isinstance(value, str) and "," in value:
        return parse_iso(value.split(","))
    result = to_int(value)
    return result if result and result > 0 else None


def normalize_key(value: str | None) -> str | None:
    """Case/punctuation-insensitive key used to merge near-identical gear names."""
    if not value:
        return None
    text = _WS_RE.sub(" ", value).strip().casefold()
    return text or None


def clean_camera(value: str | None) -> str | None:
    """Drop the duplicated brand some vendors write ('NIKON NIKON Z8')."""
    if not value:
        return None
    text = _WS_RE.sub(" ", value).strip()
    if not text:
        return None
    words = text.split(" ")
    if len(words) > 1 and words[0].casefold() == words[1].casefold():
        text = " ".join(words[1:])
    return text


def clean_lens(value: str | None) -> str | None:
    if not value:
        return None
    return _WS_RE.sub(" ", value).strip() or None


def normalize_white_balance(value: Any) -> str | None:
    """Collapse the many spellings into a small, stable vocabulary."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _WB_EXIF_VALUES.get(int(value), "unknown")
    text = _WS_RE.sub(" ", str(value)).strip()
    if not text:
        return None
    match = _UNKNOWN_RE.match(text)
    if match:
        return _WB_EXIF_VALUES.get(int(match.group(1)), "unknown")
    lowered = text.casefold()
    if lowered in WB_MAPPING:
        return WB_MAPPING[lowered]
    kelvin = _KELVIN_RE.match(lowered)
    if kelvin:
        return "manual"
    if "kelvin" in lowered or lowered.endswith(" k"):
        return "manual"
    if lowered.startswith("auto"):
        return "auto"
    return lowered


def parse_flash(value: Any) -> tuple[int | None, str | None]:
    """Return (fired, raw) where fired is 1, 0 or None when unknown."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return (1 if value else 0), None
    if isinstance(value, (int, float)):
        # EXIF flash bitmask: bit 0 set means the flash fired.
        return (1 if int(value) & 1 else 0), str(value)
    text = _WS_RE.sub(" ", str(value)).strip()
    if not text or text.casefold() in {"none", "unknown"}:
        return None, text or None
    lowered = text.casefold()
    if "no flash" in lowered or "did not fire" in lowered or "not fired" in lowered:
        return 0, text
    if "fired" in lowered:
        # 'Fired, return light not detected' still counts as a firing flash.
        return 1, text
    if lowered in {"on", "yes", "true"}:
        return 1, text
    if lowered in {"off", "no", "false", "no flash fired", "0"}:
        return 0, text
    if lowered.startswith("0x") or lowered.isdigit():
        number = to_int(text)
        if number is not None:
            return (1 if number & 1 else 0), text
    return None, text


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
_DATE_PATTERNS = (
    "%Y:%m:%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y:%m:%d %H:%M",
    "%Y-%m-%d %H:%M",
    "%Y:%m:%d",
    "%Y-%m-%d",
    "%Y:%m:%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)


def parse_date_string(value: Any) -> datetime | None:
    """Parse the many date shapes cameras write."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = _WS_RE.sub(" ", str(value)).strip()
    if not text:
        return None
    # Drop sub-second and timezone suffixes: '2024:05:03 12:33:21.1234+02:00'
    text = re.sub(r"[.]\d+", "", text, count=1)
    text = re.sub(r"(Z|[+-]\d{2}:?\d{2})$", "", text).strip()
    for pattern in _DATE_PATTERNS:
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Display formatting (used by the UI and exports)
# ---------------------------------------------------------------------------
#: Denominators cameras actually use, so that 0.016s reads as 1/60 and not 1/62.
STANDARD_SHUTTERS = (4, 8, 15, 30, 60, 125, 250, 500, 1000, 2000, 4000, 8000)


def format_shutter(seconds: float | None) -> str:
    """'1/500', '2s', '0.5s' — the way photographers expect to read it."""
    if seconds is None or seconds <= 0:
        return "—"
    if seconds >= 1:
        return f"{seconds:g}s"
    if seconds >= 0.3:
        return f"{seconds:g}s"
    best = min(STANDARD_SHUTTERS, key=lambda d: abs(1 / d - seconds))
    if abs(1 / best - seconds) <= seconds * 0.08:
        return f"1/{best}"
    denominator = max(2, round(1 / seconds))
    return f"1/{denominator}"


def format_fnumber(value: float | None) -> str:
    return "—" if value is None else f"f/{value:g}"


def format_focal(value: float | None) -> str:
    return "—" if value is None else f"{value:g}mm"


def format_resolution(width: int | None, height: int | None) -> str:
    if not width or not height:
        return "—"
    return f"{width}×{height}"


def format_megapixels(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} MP"


# ---------------------------------------------------------------------------
# Row construction
# ---------------------------------------------------------------------------
def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", []):
            return value
    return None


def build_photo_row(
    meta: dict[str, Any],
    rel_path: str,
    ext: str,
    mod_time: float | None = None,
    size: int | None = None,
    keep_raw: bool = True,
) -> tuple:
    """Build the tuple consumed by ``db.INSERTS['photo']``.

    *meta* is one exiftool JSON object, or a mapping from the legacy cache whose
    keys are the old column names.
    """
    camera = clean_camera(_first(meta.get("Model"), meta.get("CameraModelName")))
    lens = clean_lens(
        _first(meta.get("LensModel"), meta.get("Lens"), meta.get("LensID"),
               meta.get("LensType"), meta.get("LensMake"))
    )

    moment = parse_date_string(_first(meta.get("DateTimeOriginal"), meta.get("CreateDate")))
    if moment is not None:
        taken_at, source = moment.strftime("%Y-%m-%d %H:%M:%S"), DATE_SOURCE_EXIF
    elif mod_time:
        try:
            moment = datetime.fromtimestamp(mod_time)
            taken_at, source = moment.strftime("%Y-%m-%d %H:%M:%S"), DATE_SOURCE_MTIME
        except (OverflowError, OSError, ValueError):
            taken_at, source = None, DATE_SOURCE_NONE
    else:
        taken_at, source = None, DATE_SOURCE_NONE

    width, height = to_int(meta.get("ImageWidth")), to_int(meta.get("ImageHeight"))
    megapixels = (width * height / 1_000_000) if width and height else None
    flash_fired, flash_raw = parse_flash(_first(meta.get("Flash"), meta.get("FlashFire")))
    fnumber = to_float(_first(meta.get("FNumber"), meta.get("ApertureValue")))
    focal = to_float(meta.get("FocalLength"))
    focal35 = to_float(meta.get("FocalLengthIn35mmFormat"))

    raw_json = None
    if keep_raw and meta:
        try:
            raw_json = json.dumps(meta, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            raw_json = None

    return (
        rel_path,
        mod_time,
        size,
        taken_at,
        source,
        moment.year if moment else None,
        moment.month if moment else None,
        moment.day if moment else None,
        camera,
        normalize_key(camera),
        lens,
        normalize_key(lens),
        parse_iso(meta.get("ISO")),
        to_float(meta.get("ExposureTime")),
        fnumber,
        focal,
        focal35,
        flash_fired,
        flash_raw,
        normalize_white_balance(_first(meta.get("WhiteBalance"), meta.get("WhiteBalance1"))),
        file_type_of(ext),
        width,
        height,
        round(megapixels, 2) if megapixels else None,
        f"{width}x{height}" if width and height else None,
        raw_json,
    )
