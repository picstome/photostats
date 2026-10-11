"""The header-only orientation backfill.

The point of the backfill is that it reads a few hundred kilobytes instead of the
megabytes exiftool walks through, so these tests mainly prove it still gets the
right answer out of a truncated file.
"""

from __future__ import annotations

from conftest import make_library

from photostats.core.db import connect, init_db
from photostats.core.exiftool import ExifTool, find_exiftool
from photostats.core.indexer import Indexer
from photostats.core.orientation import backfill


def _stamp_orientation(paths, value: int) -> None:
    with ExifTool(find_exiftool()) as tool:
        for path in paths:
            tool.execute(["-overwrite_original", f"-Orientation#={value}", str(path)])


def _indexed(tmp_path, orientation: int):
    root = tmp_path / "photos"
    made = make_library(root, count=6, with_pairs=False)
    _stamp_orientation([m["path"] for m in made], orientation)
    db = root / "photo_stats.db"
    init_db(db)
    assert Indexer(db, root).run().ok
    return root, db


def test_backfill_reads_orientation_and_dimensions_from_the_header(tmp_path):
    root, db = _indexed(tmp_path, orientation=6)

    # A cache written before Orientation was read at all: tag and size both gone.
    conn = connect(db)
    conn.execute("UPDATE photos SET orientation_tag = NULL, width = NULL, height = NULL")
    conn.commit()
    conn.close()

    result = backfill(db, root)
    assert result.ok
    assert result.photos == 6
    assert result.filled == 6

    conn = connect(db, readonly=True)
    try:
        rows = list(conn.execute("SELECT orientation_tag, width, height FROM photos"))
    finally:
        conn.close()
    assert all(tag == 6 for tag, _, _ in rows), "the rotate tag was not read from the header"
    assert all(w is not None and h is not None for _, w, h in rows), "dimensions were not filled"


def test_backfill_leaves_raw_json_alone(tmp_path):
    root, db = _indexed(tmp_path, orientation=1)
    conn = connect(db)
    conn.execute("UPDATE photos SET orientation_tag = NULL")
    conn.commit()
    before = dict(conn.execute("SELECT rel_path, raw_json FROM photos"))
    conn.close()

    assert backfill(db, root).ok

    conn = connect(db, readonly=True)
    after = dict(conn.execute("SELECT rel_path, raw_json FROM photos"))
    conn.close()
    assert after == before, "a header read must not overwrite the full metadata"


def test_backfill_is_done_once_the_tags_are_there(tmp_path):
    root, db = _indexed(tmp_path, orientation=8)
    conn = connect(db)
    conn.execute("UPDATE photos SET orientation_tag = NULL")
    conn.commit()
    conn.close()

    assert backfill(db, root).filled == 6
    # A second run finds nothing left missing and does no work.
    second = backfill(db, root)
    assert second.ok
    assert second.photos == 0


def test_backfill_reconnects_files_left_unlinked_by_a_refresh(tmp_path):
    """Filling orientation by header must undo a half-done refresh's unlinks,
    or the next scan would still re-read every file the slow way."""
    from photostats.core.scanner import mark_all_for_extraction, refresh_in_progress

    root, db = _indexed(tmp_path, orientation=6)
    conn = connect(db)
    conn.execute("UPDATE photos SET orientation_tag = NULL")
    mark_all_for_extraction(conn)  # a refresh was started, then abandoned
    assert refresh_in_progress(conn)
    conn.close()

    assert backfill(db, root).ok

    conn = connect(db, readonly=True)
    try:
        assert not refresh_in_progress(conn), "the cache should be back at rest"
    finally:
        conn.close()
