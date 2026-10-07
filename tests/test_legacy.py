"""Import the cache written by the original console script.

The old ``photo_stats_cache.db`` stored ISO, exposure, aperture and focal length
as *text* ("1/125", "f/2.8", "50 mm"). Importing it avoids re-reading a library
that may take hours, so the text-to-number conversion has to be forgiving.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from photostats.core import db as dbmod
from photostats.core.legacy import import_legacy_cache, legacy_candidates
from photostats.core.paths import LEGACY_DB_FILENAME

LEGACY_SCHEMA = """
CREATE TABLE metadata (
    source_file TEXT PRIMARY KEY,
    mod_time REAL,
    DateTimeOriginal TEXT,
    Model TEXT,
    LensModel TEXT,
    ISO TEXT,
    ExposureTime TEXT,
    FNumber TEXT,
    FocalLength TEXT,
    Flash TEXT,
    WhiteBalance TEXT,
    ImageWidth TEXT,
    ImageHeight TEXT,
    FocalLengthIn35mmFormat TEXT
)
"""


def write_legacy_db(path: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    for row in rows:
        conn.execute(
            "INSERT INTO metadata VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            tuple(row.get(column) for column in (
                "source_file", "mod_time", "DateTimeOriginal", "Model", "LensModel", "ISO",
                "ExposureTime", "FNumber", "FocalLength", "Flash", "WhiteBalance",
                "ImageWidth", "ImageHeight", "FocalLengthIn35mmFormat",
            )),
        )
    conn.commit()
    conn.close()


def sample_row(folder: str, name: str = "IMG_0001.jpg") -> dict:
    return {
        "source_file": f"{folder}/{name}",
        "mod_time": 1700000000.0,
        "DateTimeOriginal": "2024:05:03 12:33:21",
        "Model": "NIKON Z8",
        "LensModel": "NIKKOR Z 24-70mm f/2.8 S",
        "ISO": "800",
        "ExposureTime": "1/500",
        "FNumber": "2.8",
        "FocalLength": "24 mm",
        "Flash": "Off, Did not fire",
        "WhiteBalance": "Daylight",
        "ImageWidth": "6048",
        "ImageHeight": "4024",
        "FocalLengthIn35mmFormat": "24",
    }


def test_import_converts_text_columns_to_numbers(tmp_path):
    library = tmp_path / "photos"
    library.mkdir()
    legacy = tmp_path / LEGACY_DB_FILENAME
    write_legacy_db(legacy, [sample_row(str(library))])

    db = library / "photo_stats.db"
    dbmod.init_db(db)
    conn = dbmod.connect(db)
    report = import_legacy_cache(legacy, conn, library)
    assert report.imported == 1
    assert report.skipped == 0

    row = conn.execute(
        "SELECT rel_path, iso, shutter_seconds, fnumber, focal_mm, focal35_mm, flash_fired, "
        "white_balance, year, month, day, taken_at, file_type, megapixels "
        "FROM photos"
    ).fetchone()
    assert row["rel_path"] == "IMG_0001.jpg"
    assert row["iso"] == 800
    assert row["shutter_seconds"] == 0.002
    assert row["fnumber"] == 2.8
    assert row["focal_mm"] == 24.0
    assert row["focal35_mm"] == 24.0
    assert row["flash_fired"] == 0
    assert row["white_balance"] == "daylight"
    assert (row["year"], row["month"], row["day"]) == (2024, 5, 3)
    assert row["taken_at"] == "2024-05-03 12:33:21"
    assert row["file_type"] == "jpeg"
    assert row["megapixels"] == pytest.approx(24.3, abs=0.05)
    conn.close()


def test_import_reports_rows_outside_the_library(tmp_path):
    library = tmp_path / "photos"
    library.mkdir()
    legacy = tmp_path / LEGACY_DB_FILENAME
    write_legacy_db(legacy, [
        sample_row(str(library), "inside.jpg"),
        sample_row("/somewhere/else", "outside.jpg"),
        sample_row(str(library), "also_inside.jpg"),
    ])
    db = library / "photo_stats.db"
    dbmod.init_db(db)
    conn = dbmod.connect(db)
    report = import_legacy_cache(legacy, conn, library)
    assert report.imported == 2
    assert report.skipped == 1
    assert report.skipped_paths == ("/somewhere/else/outside.jpg",)
    conn.close()


def test_import_links_files_so_a_rescan_skips_them(tmp_path):
    library = tmp_path / "photos"
    (library / "shoot").mkdir(parents=True)
    for name in ("a.jpg", "b.jpg"):
        (library / "shoot" / name).write_bytes(b"x")
    legacy = tmp_path / LEGACY_DB_FILENAME
    rows = []
    for name in ("a.jpg", "b.jpg"):
        row = sample_row(str(library / "shoot"), name)
        row["mod_time"] = (library / "shoot" / name).stat().st_mtime  # as a real scan would store
        rows.append(row)
    write_legacy_db(legacy, rows)
    db = library / "photo_stats.db"
    dbmod.init_db(db)
    conn = dbmod.connect(db)
    import_legacy_cache(legacy, conn, library)
    conn.close()

    from photostats.core.indexer import Indexer

    result = Indexer(db, library).run()
    # Files, photos and the mod_time all match, so nothing needs re-reading.
    assert result.stats.cached == 2
    assert result.extracted == 0
    assert result.photos == 2


def test_import_tolerates_missing_and_null_columns(tmp_path):
    library = tmp_path / "photos"
    library.mkdir()
    legacy = tmp_path / LEGACY_DB_FILENAME
    write_legacy_cache_row = sample_row(str(library))
    write_legacy_cache_row.update({
        "DateTimeOriginal": None, "ISO": None, "ExposureTime": None, "FNumber": None,
        "FocalLength": None, "Flash": None, "WhiteBalance": None, "LensModel": None,
        "ImageWidth": None, "ImageHeight": None,
    })
    write_legacy_db(legacy, [write_legacy_cache_row])
    db = library / "photo_stats.db"
    dbmod.init_db(db)
    conn = dbmod.connect(db)
    report = import_legacy_cache(legacy, conn, library)
    assert report.imported == 1
    row = conn.execute("SELECT iso, shutter_seconds, fnumber, flash_fired, taken_at FROM photos").fetchone()
    assert row["iso"] is None
    assert row["shutter_seconds"] is None
    assert row["fnumber"] is None
    assert row["flash_fired"] is None
    assert row["taken_at"] is not None
    # With no EXIF date the file date is used and flagged as such.
    assert conn.execute("SELECT date_source FROM photos").fetchone()["date_source"] == "mtime"
    conn.close()


def test_import_ignores_a_file_that_is_not_a_database(tmp_path):
    library = tmp_path / "photos"
    library.mkdir()
    bogus = tmp_path / LEGACY_DB_FILENAME
    bogus.write_text("this is not sqlite")
    db = library / "photo_stats.db"
    dbmod.init_db(db)
    conn = dbmod.connect(db)
    report = import_legacy_cache(bogus, conn, library)
    assert report.imported == 0
    assert report.skipped == 0
    conn.close()


def test_legacy_candidates_finds_the_file_next_to_the_library(tmp_path):
    library = tmp_path / "photos"
    library.mkdir()
    legacy = library / LEGACY_DB_FILENAME
    legacy.write_bytes(b"SQLite format 3\x00")
    assert legacy_candidates(library) == legacy
    assert legacy_candidates(tmp_path / "elsewhere") is None


def test_a_locked_database_is_reported_not_raised(tmp_path):
    """The importer must survive a write lock held elsewhere.

    The final ``meta`` write used to sit *after* the try/finally, so a busy
    database threw straight out of ``import_legacy_cache`` — the worker thread
    died without ever emitting its report, and the window sat on "Importing…"
    forever. The scan holding the walk transaction is what does it in practice.
    """
    import threading
    import time

    library = tmp_path / "photos"
    library.mkdir()
    legacy = tmp_path / LEGACY_DB_FILENAME
    write_legacy_db(legacy, [sample_row(str(library.resolve()))])
    db = library / "photo_stats.db"
    dbmod.init_db(db)

    release = threading.Event()

    def hold_the_write_lock() -> None:
        holder = dbmod.connect(db)
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO photos (rel_path) VALUES ('held.jpg')")
        release.wait(timeout=5)
        holder.rollback()
        holder.close()

    holder = threading.Thread(target=hold_the_write_lock)
    holder.start()
    time.sleep(0.3)
    try:
        conn = dbmod.connect(db, timeout=1)  # shorter than the lock is held
        report = import_legacy_cache(legacy, conn, library)  # must not raise
        conn.close()
        assert report.error == "database is locked"
        assert report.summary() == "database is locked"
    finally:
        release.set()
        holder.join(timeout=5)


def test_import_rebases_paths_when_the_library_moved(tmp_path):
    """The cache stores paths from where the library lived *then*.

    This library moved from ``…/Chema_Photo/Photoshop`` to ``…/Photoshop``.
    Stripping today's root marked all 450,000 rows "outside the folder", so
    nothing imported and the scan re-read every file.
    """
    library = tmp_path / "Photoshop"
    (library / "2020").mkdir(parents=True)
    photo = library / "2020" / "IMG_0001.jpg"
    photo.write_bytes(b"x")

    legacy = tmp_path / LEGACY_DB_FILENAME
    row = sample_row("/old/place/Chema_Photo/Photoshop/2020", "IMG_0001.jpg")
    row["mod_time"] = photo.stat().st_mtime
    write_legacy_db(legacy, [row])

    db = library / "photo_stats.db"
    dbmod.init_db(db)
    conn = dbmod.connect(db)
    report = import_legacy_cache(legacy, conn, library)

    assert report.error == ""
    assert report.imported == 1
    assert report.skipped == 0
    assert conn.execute("SELECT rel_path FROM photos").fetchone()[0] == "2020/IMG_0001.jpg"
    linked = conn.execute("SELECT COUNT(*) FROM files WHERE photo_id IS NOT NULL").fetchone()[0]
    assert linked == 1
    conn.close()


def test_import_skips_a_rebased_path_that_is_not_there(tmp_path):
    """When the roots differ, a path that is not there is a guess, not a photo."""
    library = tmp_path / "Photoshop"
    library.mkdir()
    legacy = tmp_path / LEGACY_DB_FILENAME
    write_legacy_db(legacy, [sample_row("/old/place/Photoshop/2016", "gone.jpg")])

    db = library / "photo_stats.db"
    dbmod.init_db(db)
    conn = dbmod.connect(db)
    report = import_legacy_cache(legacy, conn, library)

    assert report.imported == 0
    assert report.skipped == 1
    assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 0
    conn.close()
