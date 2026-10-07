"""Unit tests for metadata normalisation — the layer that sees real-world mess."""

from __future__ import annotations

import pytest

from photostats.core.db import PHOTO_COLUMNS
from photostats.core.parse import (
    build_photo_row,
    clean_camera,
    format_fnumber,
    format_shutter,
    normalize_key,
    normalize_white_balance,
    parse_date_string,
    parse_flash,
    parse_iso,
    to_float,
    to_int,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (800, 800.0),
        ("800", 800.0),
        (0.002, 0.002),
        ("1/125", 0.008),
        ("1/4000", 0.00025),
        ("35.0 mm", 35.0),
        ("24 mm", 24.0),
        ("f/2.8", 2.8),
        ("2.8", 2.8),
        ("ISO 400", 400.0),
        (None, None),
        ("", None),
        ("n/a", None),
        (float("inf"), None),
        (True, None),
        ([1, 2], None),
    ],
)
def test_to_float(value, expected):
    result = to_float(value)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


@pytest.mark.parametrize(
    "value,expected",
    [
        (800, 800),
        ("800", 800),
        ("ISO 6400", 6400),
        ([100, 800], 100),          # bracketed burst: take the lowest
        ("100, 400", 100),
        ([], None),
        (0, None),                   # nonsense value
        (None, None),
        ("", None),
    ],
)
def test_parse_iso(value, expected):
    assert parse_iso(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Off, Did not fire", 0),
        ("On, Fired", 1),
        ("On, Fired, Return light not detected", 1),
        ("Off", 0),
        ("No flash function", 0),
        ("No", 0),
        ("Yes", 1),
        (16, 0),        # EXIF bitmask 0x10
        (0, 0),
        (1, 1),         # bit 0 set means fired
        (0x1d, 1),
        ("0x1d", 1),
        ("0x10", 0),
        (None, None),
        ("", None),
        ("unknown", None),
        ("Something else entirely", None),
    ],
)
def test_parse_flash(value, expected):
    fired, _raw = parse_flash(value)
    assert fired == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Daylight", "daylight"),
        ("AUTO", "auto"),
        ("Auto (Ambience Priority)", "auto"),
        ("Manual Temperature (Kelvin)", "manual"),
        ("5600 K", "manual"),
        ("Custom", "manual"),
        ("Tungsten", "tungsten"),
        ("Incandescent", "tungsten"),   # folded into one bucket
        ("Overcast", "cloudy"),
        (0, "auto"),                    # EXIF enum, no -n
        (1, "manual"),
        (4, "tungsten"),                # EXIF spec value; exiftool shows "Unknown (4)"
        ("Unknown (4)", "tungsten"),
        (2, "daylight"),
        (None, None),
    ],
)
def test_normalize_white_balance(value, expected):
    assert normalize_white_balance(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "2024:05:03 12:33:21",
        "2024-05-03 12:33:21",
        "2024:05:03 12:33:21.123",
        "2024:05:03 12:33:21+02:00",
        "2024-05-03T12:33:21",
    ],
)
def test_parse_date_string_accepts_camera_formats(value):
    parsed = parse_date_string(value)
    assert (parsed.year, parsed.month, parsed.day) == (2024, 5, 3)
    assert (parsed.hour, parsed.minute, parsed.second) == (12, 33, 21)


@pytest.mark.parametrize("value", [None, "", "0000:00:00 00:00:00", "not a date", "2024"])
def test_parse_date_string_rejects_garbage(value):
    assert parse_date_string(value) is None


def test_clean_camera_removes_duplicated_brand():
    assert clean_camera("NIKON NIKON Z8") == "NIKON Z8"
    assert clean_camera("  Sony   ILCE-7RM5 ") == "Sony ILCE-7RM5"
    assert clean_camera("Canon") == "Canon"
    assert clean_camera(None) is None
    assert clean_camera("   ") is None


def test_normalize_key_is_case_and_space_insensitive():
    assert normalize_key("NIKON  Z8") == normalize_key("nikon z8")
    assert normalize_key("") is None


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0.002, "1/500"),
        (0.008, "1/125"),
        (0.016, "1/60"),       # snapped to a real shutter speed
        (0.25, "1/4"),
        (0.5, "0.5s"),
        (2.0, "2s"),
        (30.0, "30s"),
        (None, "—"),
        (0, "—"),
    ],
)
def test_format_shutter(seconds, expected):
    assert format_shutter(seconds) == expected


def test_format_fnumber():
    assert format_fnumber(2.8) == "f/2.8"
    assert format_fnumber(None) == "—"


def test_build_photo_row_matches_the_schema_width():
    """The insert SQL is generated from PHOTO_COLUMNS; a mismatch breaks writes."""
    row = build_photo_row({"Model": "X"}, "a/b.jpg", "cr2", 1700000000.0, 42)
    assert len(row) == len(PHOTO_COLUMNS.split(", "))


def test_build_photo_row_orders_columns_like_the_schema():
    columns = PHOTO_COLUMNS.split(", ")
    row = build_photo_row(
        {
            "DateTimeOriginal": "2024:05:03 12:33:21",
            "Model": "NIKON Z8",
            "LensModel": "NIKKOR Z 24-70mm f/2.8 S",
            "ISO": 400,
            "ExposureTime": 0.004,
            "FNumber": 2.8,
            "FocalLength": 24,
            "FocalLengthIn35mmFormat": 24,
            "Flash": "On, Fired",
            "WhiteBalance": "Daylight",
            "ImageWidth": 6048,
            "ImageHeight": 4024,
        },
        "IMG_1.CR2",
        "cr2",
        1700000000.0,
        4096,
    )
    values = dict(zip(columns, row, strict=True))
    assert values["rel_path"] == "IMG_1.CR2"
    assert values["taken_at"] == "2024-05-03 12:33:21"
    assert values["year"] == 2024 and values["month"] == 5 and values["day"] == 3
    assert values["camera"] == "NIKON Z8"
    assert values["camera_key"] == "nikon z8"
    assert values["lens"] == "NIKKOR Z 24-70mm f/2.8 S"
    assert values["iso"] == 400
    assert values["shutter_seconds"] == 0.004
    assert values["fnumber"] == 2.8
    assert values["focal_mm"] == 24.0
    assert values["focal35_mm"] == 24.0
    assert values["flash_fired"] == 1
    assert values["white_balance"] == "daylight"
    assert values["file_type"] == "raw"
    assert values["megapixels"] == pytest.approx(24.3, abs=0.05)


def test_build_photo_row_falls_back_to_lens_aliases():
    row = build_photo_row({"LensID": "EF24-70 2.8L", "Model": "Canon EOS R6"}, "a.jpg", "jpg")
    values = dict(zip(PHOTO_COLUMNS.split(", "), row, strict=True))
    assert values["lens"] == "EF24-70 2.8L"


def test_build_photo_row_falls_back_to_the_file_date():
    from datetime import datetime

    row = build_photo_row({}, "a.jpg", "jpg", mod_time=1700000000.0, size=10)
    values = dict(zip(PHOTO_COLUMNS.split(", "), row, strict=True))
    assert values["date_source"] == "mtime"
    # Local time, so compare against the same conversion rather than a constant.
    expected = datetime.fromtimestamp(1700000000.0).strftime("%Y-%m-%d %H:%M:%S")
    assert values["taken_at"] == expected


def test_build_photo_row_without_any_date():
    row = build_photo_row({}, "a.jpg", "jpg")
    values = dict(zip(PHOTO_COLUMNS.split(", "), row, strict=True))
    assert values["date_source"] == "none"
    assert values["taken_at"] is None
    assert values["year"] is None


def test_raw_json_is_kept_for_later_fields():
    row = build_photo_row({"Model": "X", "SomethingNew": 1}, "a.jpg", "jpg")
    values = dict(zip(PHOTO_COLUMNS.split(", "), row, strict=True))
    assert '"SomethingNew": 1' in values["raw_json"]


def test_to_int_handles_rationals():
    assert to_int("1/125") == 0
    assert to_int("35 mm") == 35
    assert to_int(None) is None
