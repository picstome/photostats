"""A RAW and a JPEG of the same shot must count once.

This is the one counting rule a photographer will notice immediately if it is
wrong, and it had no test at all: the fixture library was entirely JPEG, so
duplicate grouping was never exercised against a real RAW.

``rawfixture.write_dng`` produces a small but genuine DNG, because renaming a
JPEG to ``.NEF`` does not work — exiftool inspects the content and refuses.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from conftest import TINY_JPEG, _stamp

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def exiftool(exiftool_path):
    return exiftool_path


def index(root: Path, exiftool: str) -> sqlite3.Connection:
    """Scan *root* and hand back a connection to the resulting database."""
    from photostats.core.db import init_db
    from photostats.core.indexer import Indexer

    db_path = root / "photo_stats.db"
    init_db(db_path)
    result = Indexer(db_path=db_path, root=root, exiftool_path=exiftool,
                     workers=2, batch=50).run()
    assert result.ok, result.message
    return sqlite3.connect(db_path)


def count(con: sqlite3.Connection, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _jpeg(path: Path, **tags) -> Path:
    path.write_bytes(TINY_JPEG)
    _stamp(path, {"Make": "Canon", "Model": "Canon EOS R6", "ISO": 200,
                  "FNumber": 4.0, "ExposureTime": "1/500", "FocalLength": 50,
                  "LensModel": "RF 70-200mm F2.8",
                  "DateTimeOriginal": "2024:06:02 12:00:00", **tags})
    return path


def test_a_raw_and_its_jpeg_count_as_one_photo(tmp_path, exiftool):
    from rawfixture import write_dng

    root = tmp_path / "library"
    root.mkdir()
    write_dng(root / "IMG_0001.DNG")
    _jpeg(root / "IMG_0001.JPG")

    con = index(root, exiftool)

    assert count(con, "photos") == 1
    assert count(con, "files") == 1, "the JPEG should not even be recorded"


def test_the_raw_is_the_one_that_is_counted(tmp_path, exiftool):
    """The RAW carries the full metadata, so it has to be the survivor."""
    from rawfixture import write_dng

    root = tmp_path / "library"
    root.mkdir()
    write_dng(root / "IMG_0001.DNG", model="NIKON Z 8", iso=3200, focal=35)
    _jpeg(root / "IMG_0001.JPG", Model="Canon EOS R6", ISO=200)

    con = index(root, exiftool)

    row = con.execute("SELECT rel_path, camera, iso, focal_mm FROM photos").fetchone()
    assert row[0] == "IMG_0001.DNG"
    assert row[1] == "NIKON Z 8"
    assert row[2] == 3200


def test_a_mixed_library_counts_each_shot_once(tmp_path, exiftool):
    """Three pairs plus three lone JPEGs is nine files and six photos."""
    from rawfixture import write_dng

    root = tmp_path / "library"
    root.mkdir()
    for index_ in range(3):
        write_dng(root / f"IMG_{index_:04d}.DNG",
                  model="NIKON Z 8", iso=[100, 800, 3200][index_])
        _jpeg(root / f"IMG_{index_:04d}.JPG")
    for index_ in range(3, 6):
        _jpeg(root / f"IMG_{index_:04d}.JPG")

    con = index(root, exiftool)

    assert count(con, "photos") == 6
    assert count(con, "files") == 6
    on_disk = sorted(p.name for p in root.iterdir()
                     if p.suffix.lower() not in (".db", ".db-wal", ".db-shm"))
    assert len(on_disk) == 9, f"nine files really are on disk, got {on_disk}"


def test_extension_case_does_not_split_a_pair(tmp_path, exiftool):
    from rawfixture import write_dng

    root = tmp_path / "library"
    root.mkdir()
    write_dng(root / "IMG_0001.dng")
    _jpeg(root / "IMG_0001.jpg")

    assert count(index(root, exiftool), "photos") == 1


def test_two_different_shots_are_never_merged(tmp_path, exiftool):
    """The rule must collapse duplicates without ever losing a photo."""
    from rawfixture import write_dng

    root = tmp_path / "library"
    root.mkdir()
    write_dng(root / "A.DNG", iso=100)
    _jpeg(root / "A.JPG")
    _jpeg(root / "B.JPG", Model="Sony ILCE-7RM5", ISO=1600)

    con = index(root, exiftool)
    assert count(con, "photos") == 2


def test_three_files_of_one_shot_stay_one(tmp_path, exiftool):
    from rawfixture import write_dng

    root = tmp_path / "library"
    root.mkdir()
    write_dng(root / "A.DNG", iso=100)
    _jpeg(root / "A.JPG")
    (root / "A.TIFF").write_bytes(TINY_JPEG)
    _stamp(root / "A.TIFF", {"Make": "Canon", "Model": "Canon EOS R6", "ISO": 200})

    assert count(index(root, exiftool), "photos") == 1


def test_the_walk_reports_photos_not_files(tmp_path, exiftool):
    """What the progress line says has to match what the app counts."""
    from rawfixture import write_dng

    from photostats.core.db import init_db
    from photostats.core.indexer import Indexer

    root = tmp_path / "library"
    root.mkdir()
    for index_ in range(4):
        write_dng(root / f"S{index_}.DNG")
        _jpeg(root / f"S{index_}.JPG")

    db_path = root / "photo_stats.db"
    init_db(db_path)
    result = Indexer(db_path=db_path, root=root, exiftool_path=exiftool,
                     workers=2, batch=50).run()

    assert result.stats.files == 4, "reported 8 files for 4 photos"
    assert count(sqlite3.connect(db_path), "photos") == 4


def test_a_pair_in_different_folders_is_counted_twice(tmp_path, exiftool):
    """Documented limitation, pinned so a change to it is a deliberate one.

    Grouping happens per directory, so a RAW and its JPEG kept in separate
    folders are two photos. Grouping globally by file name alone would be
    worse: cameras reuse names like IMG_0001 every day, so it would merge
    genuinely different shots and lose photos. Doing it properly means
    matching on capture time as well, which is a change to the walk.
    """
    from rawfixture import write_dng

    root = tmp_path / "library"
    (root / "raw").mkdir(parents=True)
    (root / "jpeg").mkdir(parents=True)
    write_dng(root / "raw" / "A.DNG")
    _jpeg(root / "jpeg" / "A.JPG")

    assert count(index(root, exiftool), "photos") == 2


# -- the JPEG of a pair is never opened at all ----------------------------

def test_the_jpeg_of_a_pair_is_never_read(tmp_path, exiftool):
    """Decisive check, not a code reading: make the JPEG unreadable.

    If the indexer handed the JPEG to exiftool at any point — even to check
    whether it was the better file — this would report an error or store
    different metadata. Corrupting it proves the file is skipped, not merely
    out-voted.
    """
    from rawfixture import write_dng

    root = tmp_path / "library"
    root.mkdir()
    write_dng(root / "IMG_0001.DNG", model="NIKON Z 8", iso=3200)
    (root / "IMG_0001.JPG").write_bytes(b"\xff\xd8\xff\xe0 NOT A JPEG \x00\x01" * 20)

    con = index(root, exiftool)

    assert count(con, "photos") == 1
    row = con.execute("SELECT rel_path, camera, iso FROM photos").fetchone()
    assert row == ("IMG_0001.DNG", "NIKON Z 8", 3200)
    unreadable = con.execute(
        "SELECT COUNT(*) FROM files WHERE rel_path LIKE '%.JPG'").fetchone()[0]
    assert unreadable == 0, "the JPEG was recorded as a file"


def test_nothing_outranks_a_raw(tmp_path, exiftool):
    from conftest import TINY_JPEG as JPEG
    from rawfixture import write_dng

    root = tmp_path / "library"
    root.mkdir()
    write_dng(root / "IMG_0001.DNG", model="NIKON Z 8")
    for extension in ("JPG", "TIFF", "HEIC", "PNG"):
        other = root / f"IMG_0001.{extension}"
        other.write_bytes(JPEG)
        _stamp(other, {"Make": "Other", "Model": "Other Camera", "ISO": 100})

    con = index(root, exiftool)
    assert count(con, "photos") == 1
    assert con.execute("SELECT rel_path FROM photos").fetchone()[0] == "IMG_0001.DNG"


def test_a_tiff_beats_the_jpeg_when_there_is_no_raw(tmp_path, exiftool):
    from conftest import TINY_JPEG as JPEG

    root = tmp_path / "library"
    root.mkdir()
    (root / "IMG_0001.JPG").write_bytes(JPEG)
    _stamp(root / "IMG_0001.JPG", {"Make": "Canon", "Model": "Canon EOS R6"})
    (root / "IMG_0001.TIFF").write_bytes(JPEG)
    _stamp(root / "IMG_0001.TIFF", {"Make": "Fuji", "Model": "X-T5"})

    con = index(root, exiftool)
    assert count(con, "photos") == 1
    assert con.execute("SELECT rel_path FROM photos").fetchone()[0] == "IMG_0001.TIFF"


def test_the_skipped_jpeg_never_becomes_a_photo(tmp_path, exiftool):
    """Not just 'not counted' — it must not exist in the database at all."""
    from rawfixture import write_dng

    root = tmp_path / "library"
    root.mkdir()
    write_dng(root / "A.DNG")
    _jpeg(root / "A.JPG")
    _jpeg(root / "B.JPG")

    con = index(root, exiftool)

    paths = [row[0] for row in con.execute("SELECT rel_path FROM photos")]
    assert sorted(paths) == ["A.DNG", "B.JPG"]
    assert not any(path.endswith(".JPG") and path.startswith("A") for path in paths)
