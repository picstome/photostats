"""Header-only orientation backfill.

exiftool finds EXIF Orientation by walking a file's metadata boxes, and on a CR3
that means reading several megabytes off the disk to learn one 2-byte value. On a
slow external drive that read *is* the cost of a rescan: ~8 MB per RAW file,
hours over a large library. But Orientation and the pixel dimensions sit in the
first few kilobytes of every format we handle, so this reads only that header
into a scratch file and lets exiftool read the scratch copy. Same answer,
roughly an eighth of the I/O — checked against full reads on JPEG, CR3, ARW, DNG,
CR2 and PNG, all identical.

It writes ``orientation_tag`` and any missing ``width``/``height``, and nothing
else: ``raw_json`` is left untouched, because a header read does not carry the
lens and exposure tags a full scan records, and clobbering it with a header would
lose them.

Resumable: a cursor in ``meta`` records how far it got, advanced in the same
transaction as each batch of updates, so a stop resumes at the next batch instead
of starting over.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from . import db as dbmod
from .exiftool import ExifTool, ExifToolError, find_exiftool
from .indexer import DEFAULT_WORKERS, PHASE_EXTRACT, Progress
from .parse import to_int
from .scanner import relink_all

#: How much of each file to read. Orientation and the pixel dimensions are at the
#: front of every format we handle; the largest EXIF block seen in testing was a
#: few kilobytes, so 256 KB is comfortably past it and still tiny beside a RAW.
HEADER_BYTES = 262144

#: Photos per batch. Big enough to amortise the per-batch exiftool call, small
#: enough that a stop loses little and the progress line keeps moving.
BATCH = 400

_CURSOR_KEY = "orientation_cursor"

#: Only the tags a header read can answer, so the scratch read stays as small as
#: possible.
_HEADER_ARGS = [
    "-Orientation#", "-ImageWidth#", "-ImageHeight#",
    "-fast", "-api", "largefilesupport=1", "-charset", "filename=UTF8",
]


@dataclass
class BackfillResult:
    """Outcome of a completed or failed backfill."""

    ok: bool = False
    photos: int = 0
    filled: int = 0
    errors: int = 0
    message: str = ""


def backfill(
    db_path: Path | str,
    root: Path | str,
    workers: int = DEFAULT_WORKERS,
    on_progress: Callable[[Progress], None] | None = None,
    on_log: Callable[[str], None] | None = None,
) -> BackfillResult:
    """Fill ``orientation_tag`` for every photo still missing it, from headers."""
    result = BackfillResult()
    exe = find_exiftool()
    if not exe:
        result.message = "exiftool was not found"
        return result

    root = Path(root)
    dbmod.init_db(db_path)
    conn = dbmod.connect(db_path)
    started = time.monotonic()
    tools = [ExifTool(exe) for _ in range(max(1, min(32, workers)))]
    pool = ThreadPoolExecutor(max_workers=len(tools), thread_name_prefix="orientation")
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE orientation_tag IS NULL"
        ).fetchone()[0]
        cursor = int(dbmod.get_meta(conn, _CURSOR_KEY, "0") or 0)
        done = 0
        while True:
            rows = conn.execute(
                "SELECT id, rel_path FROM photos "
                "WHERE id > ? AND orientation_tag IS NULL ORDER BY id LIMIT ?",
                (cursor, BATCH),
            ).fetchall()
            if not rows:
                break
            # Advance past this batch even if a header turns out unreadable, so a
            # file that will never yield a tag cannot wedge the resume point.
            cursor = rows[-1]["id"]
            chunks = [rows[i::len(tools)] for i in range(len(tools))]
            futures = [
                pool.submit(_read_chunk, tools[i], root, chunks[i])
                for i in range(len(tools))
                if chunks[i]
            ]
            updates: list[tuple[int, int | None, int | None, int | None]] = []
            for future in futures:
                updates.extend(future.result())
            result.filled += _apply(conn, updates, cursor)
            result.errors += len(rows) - len(updates)
            done += len(rows)
            _emit(on_progress, total, done, started)

        # If a refresh was interrupted and handed over to this, the files are
        # still unlinked and a scan would re-read them all. Put the cache back at
        # rest so filling orientation here actually saves that read.
        relinked = relink_all(conn)
        if relinked and on_log:
            on_log(f"Reconnected {relinked:,} photos left unlinked by a refresh")

        result.ok = True
        result.photos = done
        if on_log:
            on_log(f"Filled the orientation of {result.filled:,} photos")
        return result
    except Exception as exc:  # noqa: BLE001 - reported, never raised at the CLI
        result.message = str(exc)
        if on_log:
            on_log(f"Orientation backfill failed: {exc}")
        return result
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        for tool in tools:
            tool.close()
        conn.close()


def _read_chunk(
    tool: ExifTool, root: Path, rows: list[sqlite3.Row]
) -> list[tuple[int, int | None, int | None, int | None]]:
    """Read the header of each file in *rows* and pull orientation and size out.

    The headers are copied to a scratch directory because exiftool reads from a
    path, not from bytes; the copies are a few hundred kilobytes and go to the
    local disk, so the slow read is the one from the library.
    """
    if not rows:
        return []
    out: list[tuple[int, int | None, int | None, int | None]] = []
    with tempfile.TemporaryDirectory(prefix="photostats-head-") as scratch:
        by_name: dict[str, tuple[str, int]] = {}
        for photo_id, rel_path in rows:
            try:
                with open(root / rel_path, "rb") as handle:
                    head = handle.read(HEADER_BYTES)
            except OSError:
                continue
            name = f"{photo_id}{os.path.splitext(rel_path)[1]}"
            dest = os.path.join(scratch, name)
            try:
                with open(dest, "wb") as handle:
                    handle.write(head)
            except OSError:
                continue
            by_name[name] = (dest, photo_id)
        if not by_name:
            return out
        try:
            records = tool.read_paths([dest for dest, _ in by_name.values()], tags=_HEADER_ARGS)
        except ExifToolError:
            tool.close()  # the next read starts a fresh process
            return out
        found = {os.path.basename(r.get("SourceFile", "")): r for r in records}
        for name, (_dest, photo_id) in by_name.items():
            record = found.get(name)
            if record is None:
                continue
            out.append((
                photo_id,
                to_int(record.get("Orientation")),
                to_int(record.get("ImageWidth")),
                to_int(record.get("ImageHeight")),
            ))
    return out


def _apply(
    conn: sqlite3.Connection,
    updates: list[tuple[int, int | None, int | None, int | None]],
    cursor: int,
) -> int:
    """Write one batch and advance the cursor in the same transaction."""
    conn.execute("BEGIN")
    try:
        filled = 0
        for photo_id, tag, width, height in updates:
            conn.execute(
                "UPDATE photos SET orientation_tag = ?, "
                "width = COALESCE(width, ?), height = COALESCE(height, ?) WHERE id = ?",
                (tag, width, height, photo_id),
            )
            if tag is not None:
                filled += 1
        dbmod.set_meta(conn, _CURSOR_KEY, str(cursor))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return filled


def _emit(
    on_progress: Callable[[Progress], None] | None, total: int, done: int, started: float
) -> None:
    if on_progress is None:
        return
    elapsed = time.monotonic() - started
    rate = done / elapsed if elapsed > 0 else 0.0
    eta = (total - done) / rate if rate > 0 else 0.0
    on_progress(Progress(phase=PHASE_EXTRACT, total=total, indexed=done, eta=eta))
