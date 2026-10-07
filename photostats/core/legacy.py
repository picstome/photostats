"""Import of the database produced by the original console script.

``photo_stats_cache.db`` stored ISO, exposure, aperture and focal length as
*text* ("1/125", "f/2.8", "50 mm") and every path as an absolute string.
Importing it turns a multi-hour first scan into a few seconds, so the conversion
has to be forgiving: one odd row must not lose the other 400,000.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .db import PHOTO_INSERT_SQL
from .formats import extension_of, is_raw
from .parse import build_photo_row
from .paths import LEGACY_DB_FILENAME

LEGACY_TABLE = "metadata"
LEGACY_COLUMNS = (
    "source_file", "mod_time", "DateTimeOriginal", "Model", "LensModel", "ISO",
    "ExposureTime", "FNumber", "FocalLength", "Flash", "WhiteBalance",
    "ImageWidth", "ImageHeight", "FocalLengthIn35mmFormat",
)
BATCH = 5000


@dataclass
class ImportReport:
    imported: int = 0
    skipped: int = 0
    skipped_paths: tuple[str, ...] = ()
    error: str = ""

    @property
    def total(self) -> int:
        return self.imported + self.skipped

    def summary(self) -> str:
        if self.error:
            return self.error
        text = f"Imported {self.imported:,} cached photos"
        if self.skipped:
            text += f" · {self.skipped:,} skipped (not in this folder)"
        return text


def legacy_candidates(library: Path | str | None = None) -> Path | None:
    """Where an old cache might live, nearest first."""
    seen: list[Path] = []
    if library:
        seen.append(Path(library) / LEGACY_DB_FILENAME)
    seen.append(Path.cwd() / LEGACY_DB_FILENAME)
    seen.append(Path.home() / LEGACY_DB_FILENAME)
    seen.append(Path.home() / "Documents" / LEGACY_DB_FILENAME)
    for candidate in seen:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def import_legacy_cache(
    legacy_path: Path | str,
    conn: sqlite3.Connection,
    library: Path | str,
    on_progress=None,
) -> ImportReport:
    """Copy rows from the legacy cache into the current schema.

    Paths are rewritten relative to *library*; rows pointing somewhere else are
    counted and skipped. Rows are linked to ``files`` when the file still exists
    with the same modification time, so the first real scan does no work.
    """
    report = ImportReport()
    legacy_path, library = Path(legacy_path), Path(library)
    root = str(library.resolve())

    try:
        source = sqlite3.connect(f"file:{legacy_path}?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        existing = source.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (LEGACY_TABLE,)
        ).fetchone()
        if existing is None:
            source.close()
            report.error = f"{legacy_path.name} has no '{LEGACY_TABLE}' table"
            return report
    except sqlite3.Error as exc:
        report.error = f"could not open {legacy_path.name}: {exc}"
        return report

    # The cache was written where the library lived *then*, which is not always
    # where it lives now; strip the old root, not today's.
    legacy_root = _legacy_root(source, root, root)
    rebased = os.path.normpath(legacy_root) != os.path.normpath(root)

    skipped: list[str] = []
    insert = PHOTO_INSERT_SQL
    try:
        cursor = source.execute(f"SELECT {', '.join(LEGACY_COLUMNS)} FROM {LEGACY_TABLE}")
        while True:
            chunk = cursor.fetchmany(BATCH)
            if not chunk:
                break
            conn.execute("BEGIN")
            try:
                for legacy in chunk:
                    rel_path = _relative_path(legacy["source_file"], legacy_root)
                    if rel_path is None:
                        skipped.append(legacy["source_file"])
                        continue
                    absolute = library / rel_path
                    current = _stat(absolute)
                    if rebased and current is None:
                        # The old and new roots differ, so a relative path that
                        # is not actually there is a guess. Leave it to the scan
                        # rather than record a photo at a path that does not exist.
                        skipped.append(legacy["source_file"])
                        continue
                    row = build_photo_row(
                        dict(legacy),
                        rel_path,
                        extension_of(rel_path),
                        legacy["mod_time"],
                        current.st_size if current else None,
                        keep_raw=False,
                    )
                    conn.execute(insert, row)
                    _link_file(conn, absolute, rel_path, legacy["mod_time"], current)
                    report.imported += 1
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            if on_progress:
                on_progress(report.imported)
        report.skipped = len(skipped)
        report.skipped_paths = tuple(skipped[:5])
        # Inside the try: this write is what raised "database is locked" out of
        # the importer when it sat after the finally, so the caller never got a
        # report and the thread died silently.
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('legacy_imported_from', ?)",
            (str(legacy_path),),
        )
    except sqlite3.Error as exc:
        report.error = str(exc)
    finally:
        source.close()
    return report


def _legacy_root(source: sqlite3.Connection, library_root: str, fallback: str) -> str:
    """The folder the legacy paths hang off.

    The cache stores absolute paths from wherever the library lived when it was
    written — this one from ``…/Chema_Photo/Photoshop``, which is not where it
    lives now — so stripping today's root marked every row "outside the folder"
    and imported nothing. Two ways to recover the old root, best first: the
    library's own folder name where it appears in the paths (a library that
    moved keeps its name), then the common ancestor of every path (a library
    that was renamed). Relative paths, or none with an ancestor in common, fall
    back to today's root and the old behaviour.
    """
    name = os.path.basename(os.path.normpath(library_root))
    marker = f"{os.sep}{name}{os.sep}"
    common: str | None = None
    for row in source.execute(
            f"SELECT source_file FROM {LEGACY_TABLE} WHERE source_file IS NOT NULL"):
        text = os.path.normpath(str(row[0]))
        if not os.path.isabs(text):
            return fallback
        index = text.find(marker)
        if index != -1:
            return text[: index + len(marker) - 1]
        directory = os.path.dirname(text)
        try:
            common = directory if common is None else os.path.commonpath([common, directory])
        except ValueError:
            return fallback              # mixed drives on Windows
        if common in ("", os.sep):
            return fallback
    return common or fallback


def _relative_path(source_file: str | None, root: str) -> str | None:
    """Legacy absolute path -> path relative to the library, POSIX separators."""
    if not source_file:
        return None
    text = os.path.normpath(str(source_file))
    if not os.path.isabs(text):
        return text.replace(os.sep, "/")
    try:
        common = os.path.commonpath([root, text])
    except ValueError:  # different drives on Windows
        return None
    if common != root:
        return None
    relative = os.path.relpath(text, root)
    return relative.replace(os.sep, "/")


def _stat(path):
    """``Path(path).stat()`` or None, so a missing file is not an exception."""
    try:
        return Path(path).stat()
    except OSError:
        return None


def _link_file(conn: sqlite3.Connection, absolute: Path, rel_path: str,
               mod_time: float | None, current=None) -> None:
    """Register the file so the next scan treats it as already indexed."""
    if mod_time is None:
        return
    current = current or _stat(absolute)
    if current is None or current.st_mtime != mod_time:
        # Missing, or changed since the legacy cache was written: leave it for
        # the next scan so the metadata is read again.
        return
    rel_dir, _, base = rel_path.rpartition("/")
    ext = extension_of(rel_path)
    conn.execute(
        "INSERT OR REPLACE INTO files (rel_path, rel_dir, base_name, ext, mod_time, size, "
        "is_raw, representative, photo_id) VALUES (?,?,?,?,?,?,?,1,"
        " (SELECT id FROM photos WHERE rel_path = ?))",
        (rel_path, rel_dir, base, ext, current.st_mtime, current.st_size,
         1 if is_raw(ext) else 0, rel_path),
    )


_RAW = {
    "3fr", "arw", "cr2", "cr3", "crw", "dng", "eip", "erf", "iiq", "kdc", "mdc",
    "mos", "mraw", "mrw", "nef", "nrw", "orf", "pef", "raf", "raw", "rw2", "rwl",
    "rwz", "sr2", "srf", "srw", "x3f",
}


def _insert_sql() -> str:
    from .db import PHOTO_INSERT_SQL

    return PHOTO_INSERT_SQL
