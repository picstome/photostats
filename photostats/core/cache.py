"""Which cache file a library uses, and moving it to another drive.

The photos can live on a slow external drive while the cache lives on the
machine's SSD; that is the difference between minutes and a second per screen on
a large library. This module decides where that file is for a given library, and
performs the one-time move without a rescan.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from . import db as dbmod
from .paths import same_folder


@dataclass(frozen=True)
class CacheTarget:
    """Where to open a library's cache, and why it may not be obvious.

    ``legacy`` is set when a cache written by an older build was found in the
    single fixed location; ``foreign_root`` when that file was scanned from a
    different library, in which case the caller should ask before opening it.
    """

    path: Path
    legacy: Path | None = None
    foreign_root: str | None = None


def resolve(config, photo_folder: Path | str | None) -> CacheTarget:
    """The cache a library should open, adopting one somebody moved by hand.

    The per-library path is preferred. When it does not exist yet but the fixed
    file older builds used does, that file is adopted in place as long as it was
    scanned from this library — or is a copy whose photos still resolve here,
    which is what a library copied to another disk looks like. Only a cache that
    is neither is announced as a stranger, instead of silently pruning another
    library's index.
    """
    if not photo_folder:
        return CacheTarget(config.db_path(None))
    folder = Path(photo_folder)
    target = config.db_path(folder)
    if target.exists():
        return CacheTarget(target)
    legacy = config.legacy_db_path()
    if legacy is None or legacy == target or not legacy.exists():
        return CacheTarget(target)
    owner = dbmod.root_folder(legacy)
    if owner is None or same_folder(owner, folder) or _paths_resolve(legacy, folder):
        # No recorded root (a very old cache) or a root that moved with the
        # library are not evidence of a stranger; adopting beats rescanning.
        return CacheTarget(legacy)
    return CacheTarget(target, legacy=legacy, foreign_root=owner)


def _paths_resolve(db_path: Path, folder: Path, sample: int = 8) -> bool:
    """Whether the cache's relative paths exist under *folder*.

    A library copied to another disk carries its cache and the root the cache
    recorded, which no longer matches. The paths do resolve, so it is the same
    library and the cache must be adopted. A cache from a different library
    points at files that are not here — that is the case worth asking about.
    Sampling beats scanning: a handful of ``stat`` calls on a slow drive is
    cheap, and the answer only has to be right about which case this is.
    """
    try:
        conn = dbmod.connect(db_path, readonly=True)
    except sqlite3.Error:
        return False
    try:
        rows = conn.execute("SELECT rel_path FROM files LIMIT 200").fetchall()
    except sqlite3.Error:
        return False
    finally:
        conn.close()
    picks = [row[0] for row in rows[:: max(1, len(rows) // sample)]][:sample]
    if not picks:
        return False
    found = sum(1 for rel_path in picks if (folder / rel_path).exists())
    return found * 2 >= len(picks)


def move(source: Path, target: Path) -> None:
    """Copy a cache to *target*, compacted, and verify the copy has every photo.

    ``VACUUM INTO`` writes a consistent snapshot and reclaims the free pages the
    schema v4 migration leaves behind; a plain file copy would carry both. The
    photo count is compared before returning, because losing a 538k-photo index
    to a half-written copy is hours of rescanning.
    """
    source, target = Path(source), Path(target)
    if not source.exists():
        raise FileNotFoundError(f"there is no cache at {source}")
    if target.exists():
        raise FileExistsError(f"there is already a cache at {target}")
    target.parent.mkdir(parents=True, exist_ok=True)

    # Fold the write-ahead log in first so the snapshot includes everything
    # committed, then copy through a read-only connection: a writer lock is not
    # needed and a running scan cannot be interrupted.
    conn = dbmod.connect(source)
    try:
        dbmod.checkpoint(conn)
    finally:
        conn.close()

    reader = sqlite3.connect(
        f"file:{quote(str(source))}?mode=ro", uri=True, isolation_level=None
    )
    try:
        reader.execute("VACUUM INTO ?", (str(target),))
    finally:
        reader.close()

    try:
        before, after = _photo_count(source), _photo_count(target)
        if before != after:
            raise sqlite3.DatabaseError(
                f"the copy has {after:,} photos and the original {before:,}"
            )
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def _photo_count(path: Path) -> int:
    conn = dbmod.connect(path, readonly=True)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0])
    finally:
        conn.close()
