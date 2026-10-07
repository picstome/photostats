"""Phase A of indexing: walk the folder tree, group duplicates, diff the cache.

The walk is resumable. The list of directories still to visit is persisted in
``scan_state.walk_stack`` in the same transaction as the rows it produced, so an
interrupted scan continues at the next unvisited directory instead of starting
over. Because every insert is idempotent, a directory interrupted mid-way is
simply visited again.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from .formats import extension_of, is_allowed, is_raw, priority_of

ROOT_DIR = ""  # stored form of the root directory itself


@dataclass
class WalkStats:
    """Counters accumulated across the whole walk."""

    files: int = 0
    new: int = 0
    updated: int = 0
    cached: int = 0
    removed: int = 0
    errors: int = 0
    directories: int = 0
    bytes_seen: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "files": self.files,
            "new": self.new,
            "updated": self.updated,
            "cached": self.cached,
            "removed": self.removed,
            "errors": self.errors,
            "directories": self.directories,
        }


@dataclass
class WalkEvent:
    """Emitted per directory so the UI can show progress."""

    directory: str
    files: int
    stats: WalkStats = field(default_factory=WalkStats)


def scan_root(
    conn: sqlite3.Connection,
    root: Path,
    stats: WalkStats,
    on_directory: callable | None = None,
    commit_every: int = 2000,
    should_stop: callable | None = None,
) -> bool:
    """Walk *root*, insert/refresh ``files`` rows. Returns False if stopped.

    Existing rows that no longer exist on disk are removed together with their
    photo rows, so deleted or moved files disappear from the statistics.
    """
    root = Path(root).resolve()
    conn.execute("BEGIN")
    try:
        conn.execute(
            "INSERT OR IGNORE INTO scan_state (id, phase, walk_stack) VALUES (1, 'walk', ?)",
            (_encode_stack([ROOT_DIR]),),
        )
        # Only a walk that never finished may resume: anything else needs a fresh
        # pass so that new, changed and deleted files are picked up.
        row = conn.execute("SELECT phase, walk_stack FROM scan_state WHERE id = 1").fetchone()
        resuming = bool(row) and row[0] == "walk" and bool(row[1]) and row[1] != "[]"
        stack = _decode_stack(row[1]) if resuming else [ROOT_DIR]
        if not resuming:
            # `dirs` lists what *this* walk has seen. Start over so that folders
            # deleted since the last run are recognised as gone afterwards.
            conn.execute("DELETE FROM dirs")
        conn.execute(
            "UPDATE scan_state SET phase = 'walk', walk_stack = ?, updated_at = ? WHERE id = 1",
            (_encode_stack(stack), time.time()),
        )
    except sqlite3.OperationalError:
        conn.rollback()
        conn.execute("BEGIN")
        stack = [ROOT_DIR]
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('root_folder', ?)", (str(root),))
    _clear_scan_counters(conn)

    pending = 0
    try:
        while stack:
            if should_stop is not None and should_stop():
                _save_stack(conn, stack)
                conn.commit()
                return False
            rel_dir = stack.pop()
            directory = root / rel_dir if rel_dir else root
            subdirs, files = _scan_one_directory(conn, root, rel_dir, directory, stats)
            conn.execute(
                "INSERT OR REPLACE INTO dirs (rel_dir, scanned_at) VALUES (?, ?)",
                (rel_dir, time.time()),
            )
            conn.execute("UPDATE scan_state SET partial_dir = ? WHERE id = 1", (rel_dir,))
            stack.extend(subdirs)
            _save_stack(conn, stack)
            pending += len(files)
            stats.directories += 1
            if on_directory is not None:
                on_directory(WalkEvent(rel_dir, len(files), stats))
            if pending >= commit_every:
                _update_scan_counters(conn, stats)
                conn.commit()
                conn.execute("BEGIN")
                pending = 0
        _update_scan_counters(conn, stats)
        conn.execute("UPDATE scan_state SET phase = 'extract', partial_dir = NULL WHERE id = 1")
        conn.commit()
        return True
    except BaseException:
        conn.rollback()
        raise


# ---------------------------------------------------------------------------
# Per-directory work
# ---------------------------------------------------------------------------
def _scan_one_directory(
    conn: sqlite3.Connection,
    root: Path,
    rel_dir: str,
    directory: Path,
    stats: WalkStats,
) -> tuple[list[str], list[str]]:
    existing = {
        row["rel_path"]: (row["id"], row["mod_time"], row["size"], row["photo_id"], row["representative"])
        for row in conn.execute(
            "SELECT id, rel_path, mod_time, size, photo_id, representative "
            "FROM files WHERE rel_dir = ?",
            (rel_dir,),
        )
    }

    # Collect this directory's photo files, then pick one per base name.
    candidates: dict[str, tuple[int, str, Path, float, int]] = {}
    subdirs: list[str] = []
    unreadable = 0
    try:
        entries = list(os.scandir(directory))
    except OSError:
        unreadable = 1
        entries = []
    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False):
                subdirs.append(f"{rel_dir}/{entry.name}" if rel_dir else entry.name)
                continue
            if not entry.is_file(follow_symlinks=True):
                continue
            ext = extension_of(entry.name)
            if not is_allowed(entry.name):
                continue
            stat = entry.stat()
        except OSError:
            unreadable += 1
            continue
        base = entry.name[: -len(ext) - 1] if ext else entry.name
        rank = priority_of(ext)
        previous = candidates.get(base)
        if previous is None or rank > previous[0]:
            candidates[base] = (rank, entry.name, Path(entry.path), stat.st_mtime, stat.st_size)

    seen: set[str] = set()
    for base, (_, filename, _path, mod_time, size) in candidates.items():
        rel_path = f"{rel_dir}/{filename}" if rel_dir else filename
        seen.add(rel_path)
        stats.files += 1
        stats.bytes_seen += size
        record = existing.get(rel_path)
        if record is None:
            conn.execute(
                "INSERT INTO files (rel_path, rel_dir, base_name, ext, mod_time, size, "
                "is_raw, representative, photo_id) VALUES (?,?,?,?,?,?,?,1,NULL)",
                (rel_path, rel_dir, base, extension_of(filename), mod_time, size,
                 1 if is_raw(extension_of(filename)) else 0),
            )
            stats.new += 1
            continue
        file_id, old_mod, old_size, photo_id, _ = record
        changed = old_mod != mod_time or old_size != size
        if changed:
            conn.execute(
                "UPDATE files SET mod_time = ?, size = ?, representative = 1 WHERE id = ?",
                (mod_time, size, file_id),
            )
            if photo_id is not None:
                conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
                conn.execute("UPDATE files SET photo_id = NULL WHERE id = ?", (file_id,))
            stats.updated += 1
        else:
            stats.cached += 1

    # Files that lost the grouping fight, or vanished, are dropped.
    for rel_path, (file_id, _mod, _size, photo_id, representative) in existing.items():
        if rel_path in seen:
            continue
        if representative:
            conn.execute("DELETE FROM photos WHERE rel_path = ?", (rel_path,))
            stats.removed += 1
        else:
            stats.removed += 1
        conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
        del photo_id

    stats.errors += unreadable
    return subdirs, list(seen)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _encode_stack(stack: list[str]) -> str:
    import json

    return json.dumps(stack)


def _decode_stack(raw: str) -> list[str]:
    import json

    try:
        stack = json.loads(raw)
    except (TypeError, ValueError):
        return [ROOT_DIR]
    return [str(item) for item in stack] if isinstance(stack, list) else [ROOT_DIR]


def _save_stack(conn: sqlite3.Connection, stack: list[str]) -> None:
    conn.execute("UPDATE scan_state SET walk_stack = ?, updated_at = ? WHERE id = 1",
                 (_encode_stack(stack), time.time()))


def _clear_scan_counters(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE scan_state SET total_files = 0, new_count = 0, cached_count = 0, "
        "updated_count = 0, error_count = 0, started_at = ? WHERE id = 1",
        (time.time(),),
    )


def _update_scan_counters(conn: sqlite3.Connection, stats: WalkStats) -> None:
    conn.execute(
        "UPDATE scan_state SET total_files = ?, new_count = ?, cached_count = ?, "
        "updated_count = ?, error_count = ? WHERE id = 1",
        (stats.files, stats.new, stats.cached, stats.updated, stats.errors),
    )


def representatives_needing_extraction(
    conn: sqlite3.Connection, after_id: int, limit: int
) -> list[tuple[int, str]]:
    """Next files whose metadata is not stored yet, in id order.

    ``photo_id IS NULL`` is the resume mechanism between runs: a row is only
    linked to its photo in the same transaction that writes that photo, so a
    crash or cancel can never leave a file skipped. ``after_id`` is therefore a
    *within-run* read-ahead offset used to avoid queueing the same batch twice;
    never pass the persisted ``scan_state.extract_cursor`` here, because a file
    changed by an earlier scan keeps its original id and must still be re-read.
    """
    rows = conn.execute(
        "SELECT id, rel_path FROM files WHERE photo_id IS NULL AND id > ? ORDER BY id LIMIT ?",
        (after_id, limit),
    ).fetchall()
    return [(row["id"], row["rel_path"]) for row in rows]


def prune_stale_dirs(conn: sqlite3.Connection, stats: WalkStats | None = None) -> int:
    """Forget files (and their photos) whose directory no longer exists.

    The walk only visits directories that are present on disk, so a folder that
    was deleted or renamed since the last run would otherwise linger in the
    statistics. Returns how many files were dropped.
    """
    stale = conn.execute(
        "SELECT id, photo_id FROM files WHERE rel_dir NOT IN (SELECT rel_dir FROM dirs)"
    ).fetchall()
    if not stale:
        return 0
    photo_ids = [(row["photo_id"],) for row in stale if row["photo_id"] is not None]
    file_ids = [(row["id"],) for row in stale]
    conn.execute("BEGIN")
    try:
        if photo_ids:
            conn.executemany("DELETE FROM photos WHERE id = ?", photo_ids)
        conn.executemany("DELETE FROM files WHERE id = ?", file_ids)
        # Directories with no files left are noise; drop them so the table
        # keeps tracking the tree rather than growing forever.
        conn.execute("DELETE FROM dirs WHERE rel_dir NOT IN (SELECT DISTINCT rel_dir FROM files)")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    if stats is not None:
        stats.removed += len(stale)
    return len(stale)
