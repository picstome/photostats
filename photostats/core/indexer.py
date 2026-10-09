"""Indexing: walk the tree, then read metadata for files we do not have yet.

Two phases, both resumable:

* **walk** (:mod:`.scanner`) — enumerates files, groups RAW+JPEG duplicates and
  diffs against the cache. Persists the pending directory stack, so an
  interrupted scan continues at the next unvisited directory.
* **extract** — reads metadata with a pool of persistent exiftool processes and
  writes it in batches. Each batch commits its rows *and* the extraction cursor
  atomically, so a crash or a cancel resumes at the last finished batch.

Nothing here touches Qt: the UI wraps this and forwards the progress callback to
signals, which keeps the engine testable and usable from the command line.
"""

from __future__ import annotations

import os
import queue
import sqlite3
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

from . import db as dbmod
from .exiftool import ExifTool, ExifToolError, exiftool_version, find_exiftool
from .parse import build_photo_row
from .scanner import (
    WalkStats,
    prune_stale_dirs,
    representatives_needing_extraction,
    scan_root,
)

PHASE_IDLE = "idle"
PHASE_WALK = "walk"
PHASE_EXTRACT = "extract"
PHASE_DONE = "done"
PHASE_PAUSED = "paused"

#: Files per exiftool batch. Progress is reported per finished batch, so this is
#: also how smooth the progress bar moves: with a very large batch the bar sits
#: still for the whole read and then jumps.
#:
#: Measured on 4,000 files over 10 cores, eight parallel reads, five interleaved
#: runs each: 1,496 files/s at 50, 1,395 at 100, 1,389 at 250 and 943 at 1200.
#: Between 50 and 250 the difference is only a few percent, but 1200 is 40% worse
#: because each worker spends longer idle waiting for a full batch. 50 is the
#: fastest and also the smoothest, advancing the bar every fifty photos.
DEFAULT_BATCH = 50

#: Concurrent exiftool processes. This is the only setting that really matters.
#: Reading EXIF is per-process CPU work inside exiftool's Perl runtime, so it
#: parallelises almost perfectly; on the same benchmark 1 worker managed 552
#: files/s, 4 managed 1,060 and 8 managed 1,496. That is the whole story: nearly
#: 3x for one number.
#:
#: Past the core count the gain stops being worth it, so the default is
#: ``cores - 2`` capped at 12, leaving two cores for the window and the database
#: writer to keep the app usable mid-scan. Twelve was the fastest single cell in
#: the benchmark, but only by about 8%, and it was slower than eight at the
#: larger batch sizes, so this stays close to the core count rather than above.
DEFAULT_WORKERS = min(12, max(2, (os.cpu_count() or 4) - 2))
_PROGRESS_INTERVAL = 0.25


@dataclass
class Progress:
    """Snapshot handed to the progress callback a few times per second."""

    phase: str = PHASE_IDLE
    detail: str = ""
    total: int = 0
    indexed: int = 0
    pending: int = 0
    cached: int = 0
    new: int = 0
    updated: int = 0
    errors: int = 0
    elapsed: float = 0.0
    rate: float = 0.0
    eta: float = 0.0

    @property
    def fraction(self) -> float:
        if self.phase in (PHASE_IDLE, PHASE_DONE):
            return 1.0
        if self.total <= 0:
            return 0.0
        return max(0.0, min(1.0, self.indexed / self.total))


@dataclass
class IndexResult:
    """Outcome of a completed, paused or failed run."""

    ok: bool = False
    paused: bool = False
    cancelled: bool = False
    stats: WalkStats = field(default_factory=WalkStats)
    extracted: int = 0
    photos: int = 0
    errors: int = 0
    exiftool: str = ""
    message: str = ""

    @property
    def summary(self) -> str:
        if self.paused:
            return f"Paused · {self.photos:,} photos indexed so far"
        if not self.ok:
            return self.message or "Scan failed"
        parts = [f"{self.photos:,} photos"]
        if self.extracted:
            parts.append(f"{self.extracted:,} newly read")
        if self.stats.cached:
            parts.append(f"{self.stats.cached:,} from cache")
        if self.errors:
            parts.append(f"{self.errors:,} unreadable")
        return ", ".join(parts)


class Indexer:
    """Runs one scan. ``cancel`` may be called from any thread."""

    def __init__(
        self,
        db_path: Path | str,
        root: Path | str,
        exiftool_path: str | None = None,
        workers: int = DEFAULT_WORKERS,
        batch: int = DEFAULT_BATCH,
        on_progress: Callable[[Progress], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.root = Path(root)
        self.exiftool_path = exiftool_path
        self.workers = max(1, min(32, workers))
        self.batch = max(10, min(4000, batch))
        #: The batch actually requested while reading. Shrinks if the drive
        #: cannot serve ``workers * batch`` files at once (see _read_with).
        self._effective_batch = self.batch
        self._on_progress = on_progress
        self._on_log = on_log
        self._cancel = threading.Event()
        self._tool_pool: queue.SimpleQueue[ExifTool] = queue.SimpleQueue()
        self._indexed = 0
        #: Files whose metadata has been read, which runs ahead of the writes.
        self._read = 0
        self._total = 0
        self._cursor = 0
        self._extracted = 0
        self._errors = 0
        self._started = 0.0
        self._last_emit = 0.0
        self.stats = WalkStats()

    # -- control -----------------------------------------------------------
    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def log(self, message: str) -> None:
        if self._on_log:
            self._on_log(message)

    # -- entry point -------------------------------------------------------
    def run(self) -> IndexResult:
        result = IndexResult()
        exe = find_exiftool(self.exiftool_path)
        if not exe:
            result.message = "exiftool was not found"
            self.log(result.message)
            return result
        result.exiftool = exiftool_version(exe)

        self._started = time.monotonic()
        self._cancel.clear()
        dbmod.init_db(self.db_path)
        conn = dbmod.connect(self.db_path)
        try:
            if self._resume(conn):
                self.log("Resuming the scan from where it stopped")
            self._total = self._count_representatives(conn)

            self._emit(phase=PHASE_WALK, force=True)
            completed = scan_root(
                conn,
                self.root,
                self.stats,
                on_directory=lambda event: self._emit(phase=PHASE_WALK, detail=event.directory),
                should_stop=self._cancel.is_set,
            )
            self._total = self._count_representatives(conn)
            self._indexed = self._count_indexed(conn)
            result.stats = self.stats
            if not completed:
                return self._pause(conn, result)

            prune_stale_dirs(conn, self.stats)
            self._extract(conn, exe, result)
            if self._cancel.is_set():
                return self._pause(conn, result)

            conn.execute(
                "UPDATE scan_state SET phase = ?, walk_stack = '[]', partial_dir = NULL, "
                "updated_at = ? WHERE id = 1",
                (PHASE_DONE, time.time()),
            )
            conn.commit()
            conn.execute("ANALYZE")
            conn.commit()
            dbmod.checkpoint(conn)

            result.ok = True
            result.photos = self._count_indexed(conn)
            result.extracted = self._extracted
            result.errors = self._errors
            self._emit(phase=PHASE_DONE, force=True)
            return result
        except Exception as exc:
            dbmod.checkpoint(conn)
            result.message = str(exc)
            self.log(f"Scan failed: {exc}")
            return result
        finally:
            while not self._tool_pool.empty():
                tool = self._tool_pool.get()
                tool.close()
            conn.close()

    # -- phase B -----------------------------------------------------------
    def _extract(self, conn: sqlite3.Connection, exe: str, result: IndexResult) -> None:
        # Read-ahead offset for this run only; see scanner's docstring.
        read_ahead = 0
        tools = [ExifTool(exe) for _ in range(self.workers)]
        for tool in tools:
            self._tool_pool.put(tool)

        pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="exiftool")
        futures: dict = {}
        try:
            batch = self._next_batch(conn, read_ahead)
            self._emit(phase=PHASE_EXTRACT, force=True)
            while batch or futures:
                if self._cancel.is_set():
                    return
                while batch and len(futures) < self.workers * 2:
                    futures[pool.submit(self._read_batch, batch)] = batch
                    read_ahead = max(file_id for file_id, _ in batch)
                    batch = self._next_batch(conn, read_ahead)
                    if batch:
                        self._emit(phase=PHASE_EXTRACT)
                if not futures:
                    break
                done, _pending = wait(list(futures), return_when=FIRST_COMPLETED)
                for future in done:
                    futures.pop(future, None)
                    try:
                        rows = future.result()
                    except ExifToolError as exc:
                        self.log(f"exiftool failed on a batch: {exc}")
                        self._errors += 1
                        continue
                    except Exception as exc:  # defensive: never lose the whole scan
                        self.log(f"unexpected error while reading metadata: {exc}")
                        self._errors += 1
                        continue
                    # Advance the reported progress as soon as the metadata is
                    # read, not when the write lands: the read is the slow part,
                    # and waiting for the write leaves the bar frozen at 0%.
                    self._read += len(rows)
                    self._emit(phase=PHASE_EXTRACT)
                    written, highest = self._write_batch(conn, rows)
                    if written:
                        self._extracted += written
                        self._indexed += written
                        self._cursor = max(self._cursor, highest)
                    self._emit(phase=PHASE_EXTRACT)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
            for _ in range(self.workers):
                tool = self._tool_pool.get()
                tool.close()
        result.extracted = self._extracted

    def _read_batch(self, batch: list[tuple[int, str]]) -> list[tuple[int, str, dict]]:
        """Read one batch with a borrowed exiftool worker."""
        tool: ExifTool = self._tool_pool.get()
        try:
            return self._read_with(tool, batch)
        finally:
            self._tool_pool.put(tool)

    def _read_with(
        self, tool: ExifTool, batch: list[tuple[int, str]]
    ) -> list[tuple[int, str, dict]]:
        """Read a batch, halving it on failure instead of losing all of it.

        exiftool times out on a batch that is too much for the drive to serve
        in one go — 250 files across 16 workers on an external USB drive is
        enough — and it dies outright on a file it cannot parse. Retrying the
        whole batch then fails the same way, and the previous code dropped all
        250 photos with it. Splitting recurses down to single files, so the
        slow part still gets read and one bad file costs one file, not a batch.
        """
        absolute = [str(self.root / rel_path) for _, rel_path in batch]
        try:
            records = tool.read_paths(absolute)
        except ExifToolError as exc:
            tool.close()  # the next read_paths starts a fresh process
            if len(batch) > 1:
                # The drive could not serve this many files across the workers
                # in time. Shrink what the next batches ask for, so they do not
                # have to time out to learn the same thing; then halve this one
                # and try again, down to single files.
                if len(batch) == self._effective_batch and self._effective_batch > 10:
                    self._effective_batch = max(10, len(batch) // 5)
                    self.log(f"reading fewer files per batch ({self._effective_batch}) "
                             f"to suit this drive: {exc}")
                middle = len(batch) // 2
                return (self._read_with(tool, batch[:middle])
                        + self._read_with(tool, batch[middle:]))
            self._errors += 1
            self.log(f"could not read {batch[0][1]}: {exc}")
            return []
        by_path = {record.get("SourceFile"): record for record in records}
        out = [(file_id, rel_path, by_path[str(self.root / rel_path)])
               for file_id, rel_path in batch
               if str(self.root / rel_path) in by_path]
        missing = len(batch) - len(out)
        if missing:
            self._errors += missing
            self.log(f"{missing} file(s) could not be read by exiftool")
        return out

    def _write_batch(
        self, conn: sqlite3.Connection, rows: list[tuple[int, str, dict]]
    ) -> tuple[int, int]:
        """Persist one batch, advancing the cursor in the same transaction.

        Returns ``(rows written, highest file id covered)``.
        """
        if not rows:
            return 0, self._cursor
        existing: dict[str, int] = {}
        paths = [rel_path for _, rel_path, _ in rows]
        for start in range(0, len(paths), 400):
            chunk = paths[start : start + 400]
            existing.update({
                row["rel_path"]: row["id"]
                for row in conn.execute(
                    f"SELECT id, rel_path FROM photos WHERE rel_path IN ({','.join('?' * len(chunk))})",
                    chunk,
                )
            })

        conn.execute("BEGIN")
        written = 0
        try:
            for file_id, rel_path, meta in rows:
                info = conn.execute(
                    "SELECT mod_time, size, ext FROM files WHERE id = ?", (file_id,)
                ).fetchone()
                if info is None:
                    continue
                try:
                    row = build_photo_row(meta, rel_path, info["ext"], info["mod_time"],
                                          info["size"])
                except Exception as exc:
                    # One file with a value the parser cannot handle must not
                    # take the whole scan down: skip it and keep the other
                    # thousands in the batch.
                    self._errors += 1
                    self.log(f"could not read the metadata of {rel_path}: {exc}")
                    continue
                photo_id = existing.get(rel_path)
                if photo_id is None:
                    photo_id = conn.execute(dbmod.PHOTO_INSERT_SQL, row).lastrowid
                    existing[rel_path] = photo_id
                else:
                    # row[0] is rel_path, which the primary key already carries.
                    conn.execute(dbmod.PHOTO_UPDATE_SQL, (*row[1:], photo_id))
                conn.execute("UPDATE files SET photo_id = ? WHERE id = ?", (photo_id, file_id))
                written += 1
            highest = max(file_id for file_id, _, _ in rows)
            conn.execute(
                "UPDATE scan_state SET extract_cursor = ?, error_count = ?, updated_at = ? "
                "WHERE id = 1",
                (highest, self._errors, time.time()),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return written, highest

    def _next_batch(self, conn: sqlite3.Connection, after_id: int) -> list[tuple[int, str]]:
        return representatives_needing_extraction(conn, after_id, self._effective_batch)

    # -- bookkeeping -------------------------------------------------------
    def _resume(self, conn: sqlite3.Connection) -> bool:
        row = conn.execute("SELECT phase FROM scan_state WHERE id = 1").fetchone()
        return bool(row) and row[0] not in (PHASE_IDLE, PHASE_DONE, "", None)

    def _count_representatives(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT COUNT(*) FROM files WHERE representative = 1").fetchone()
        return int(row[0]) if row else 0

    def _count_indexed(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT COUNT(*) FROM files WHERE representative = 1 AND photo_id IS NOT NULL"
        ).fetchone()
        return int(row[0]) if row else 0

    def _pause(self, conn: sqlite3.Connection, result: IndexResult) -> IndexResult:
        conn.execute(
            "UPDATE scan_state SET phase = ?, updated_at = ? WHERE id = 1",
            (PHASE_PAUSED, time.time()),
        )
        conn.commit()
        dbmod.checkpoint(conn)
        result.paused = True
        result.cancelled = True
        result.photos = self._count_indexed(conn)
        result.errors = self._errors
        result.stats = self.stats
        self._emit(phase=PHASE_PAUSED, force=True)
        return result

    # -- progress ----------------------------------------------------------
    def _emit(self, phase: str, detail: str = "", force: bool = False) -> None:
        if self._on_progress is None:
            return
        now = time.monotonic()
        if not force and now - self._last_emit < _PROGRESS_INTERVAL:
            return
        self._last_emit = now
        progress = Progress(
            phase=phase,
            detail=detail,
            total=self._total,
            indexed=self._walk_files if phase == PHASE_WALK else max(self._read, self._indexed),
            pending=max(0, self._total - max(self._read, self._indexed))
            if phase != PHASE_WALK
            else 0,
            cached=self.stats.cached,
            new=self.stats.new,
            updated=self.stats.updated,
            errors=self._errors or self.stats.errors,
        )
        progress.elapsed = now - self._started
        if progress.elapsed > 0.4:
            progress.rate = progress.indexed / progress.elapsed
            if progress.rate > 0 and progress.pending:
                progress.eta = progress.pending / progress.rate
        self._on_progress(progress)

    @property
    def _walk_files(self) -> int:
        return self.stats.files
