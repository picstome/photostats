"""SQLite schema, connections and migrations.

Design notes
------------
* Photo paths are stored **relative** to the folder that contains the database so
  the file stays portable between machines.
* One connection per thread; SQLite objects are not shared across threads.
* Every phase of a scan commits rows *and* its cursor in the same transaction, so
  an interrupted scan resumes exactly where it stopped.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from urllib.parse import quote

SCHEMA_VERSION = 1

# Bump when adding a migration to _migrate().
SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    id              INTEGER PRIMARY KEY,
    rel_path        TEXT    NOT NULL UNIQUE,
    mod_time        REAL,
    size            INTEGER,
    taken_at        TEXT,
    date_source     TEXT,
    year            INTEGER,
    month           INTEGER,
    day             INTEGER,
    camera          TEXT,
    camera_key      TEXT,
    lens            TEXT,
    lens_key        TEXT,
    iso             INTEGER,
    shutter_seconds REAL,
    fnumber         REAL,
    focal_mm        REAL,
    focal35_mm      REAL,
    flash_fired     INTEGER,
    flash_raw       TEXT,
    white_balance   TEXT,
    file_type       TEXT,
    width           INTEGER,
    height          INTEGER,
    megapixels      REAL,
    resolution      TEXT,
    raw_json        TEXT
);
CREATE INDEX IF NOT EXISTS ix_photos_date   ON photos(taken_at);
CREATE INDEX IF NOT EXISTS ix_photos_year   ON photos(year);
CREATE INDEX IF NOT EXISTS ix_photos_month  ON photos(year, month);
CREATE INDEX IF NOT EXISTS ix_photos_cam    ON photos(camera_key);
CREATE INDEX IF NOT EXISTS ix_photos_lens   ON photos(lens_key);
CREATE INDEX IF NOT EXISTS ix_photos_iso    ON photos(iso);
CREATE INDEX IF NOT EXISTS ix_photos_shutter ON photos(shutter_seconds);
CREATE INDEX IF NOT EXISTS ix_photos_fnum   ON photos(fnumber);
CREATE INDEX IF NOT EXISTS ix_photos_focal  ON photos(focal_mm);
CREATE INDEX IF NOT EXISTS ix_photos_flash  ON photos(flash_fired);
CREATE INDEX IF NOT EXISTS ix_photos_wb     ON photos(white_balance);
CREATE INDEX IF NOT EXISTS ix_photos_type   ON photos(file_type);
CREATE INDEX IF NOT EXISTS ix_photos_res    ON photos(resolution);

CREATE TABLE IF NOT EXISTS files (
    id             INTEGER PRIMARY KEY,
    rel_path       TEXT    NOT NULL UNIQUE,
    rel_dir        TEXT    NOT NULL,
    base_name      TEXT    NOT NULL,
    ext            TEXT    NOT NULL,
    mod_time       REAL,
    size           INTEGER,
    is_raw         INTEGER NOT NULL DEFAULT 0,
    representative INTEGER NOT NULL DEFAULT 1,
    photo_id       INTEGER REFERENCES photos(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_files_dir   ON files(rel_dir);
CREATE INDEX IF NOT EXISTS ix_files_base  ON files(rel_dir, base_name);
CREATE INDEX IF NOT EXISTS ix_files_photo ON files(photo_id);
CREATE INDEX IF NOT EXISTS ix_files_rep   ON files(representative, id);

CREATE TABLE IF NOT EXISTS dirs (
    rel_dir   TEXT PRIMARY KEY,
    scanned_at REAL
);

CREATE TABLE IF NOT EXISTS scan_state (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    phase          TEXT    NOT NULL DEFAULT 'idle',
    walk_stack     TEXT,
    partial_dir    TEXT,
    extract_cursor INTEGER NOT NULL DEFAULT 0,
    total_files    INTEGER NOT NULL DEFAULT 0,
    new_count      INTEGER NOT NULL DEFAULT 0,
    cached_count   INTEGER NOT NULL DEFAULT 0,
    updated_count  INTEGER NOT NULL DEFAULT 0,
    error_count    INTEGER NOT NULL DEFAULT 0,
    started_at     REAL,
    updated_at     REAL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

PHOTO_COLUMNS = (
    "rel_path, mod_time, size, taken_at, date_source, year, month, day, camera, camera_key, "
    "lens, lens_key, iso, shutter_seconds, fnumber, focal_mm, focal35_mm, flash_fired, flash_raw, "
    "white_balance, file_type, width, height, megapixels, resolution, raw_json"
)

_COLUMN_LIST = PHOTO_COLUMNS.split(", ")

#: Statements built from :data:`PHOTO_COLUMNS` so that the schema and the writes
#: can never drift apart. ``build_photo_row`` must return exactly this many values.
PHOTO_INSERT_SQL = (
    f"INSERT INTO photos ({PHOTO_COLUMNS}) VALUES ({','.join('?' * len(_COLUMN_LIST))})"
)
PHOTO_UPDATE_SQL = (
    "UPDATE photos SET "
    + ", ".join(f"{name} = ?" for name in _COLUMN_LIST[1:])
    + " WHERE id = ?"
)


def connect(db_path: Path | str, readonly: bool = False, timeout: float = 30.0) -> sqlite3.Connection:
    """Open a tuned connection. Callers own the returned connection."""
    path = Path(db_path)
    if readonly:
        if not path.exists():
            raise sqlite3.OperationalError(f"database does not exist: {path}")
        # Percent-encode: a folder named "photos?x" or containing "#" would
        # otherwise corrupt the URI.
        conn = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=timeout)
        conn.row_factory = sqlite3.Row
        return conn
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=timeout, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -20000")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | str) -> None:
    """Create the schema if needed and run any pending migrations."""
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.execute(
            "INSERT OR IGNORE INTO scan_state (id, phase) VALUES (1, 'idle')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    finally:
        conn.close()


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))


def checkpoint(conn: sqlite3.Connection) -> None:
    """Fold the WAL back into the main file so the .db is self-contained.

    Run on clean shutdown: copying a single .db from another machine only works if
    the write-ahead log has been merged in.
    """
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply forward migrations for databases created by older versions."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        return
    version = int(row[0])
    if version >= SCHEMA_VERSION:
        return
    # Future migrations go here, one `if version < N:` block each.
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                 (str(SCHEMA_VERSION),))
