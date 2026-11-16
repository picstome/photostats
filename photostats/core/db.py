"""SQLite schema, connections and migrations.

Design notes
------------
* Photo paths are stored **relative to the photo library**, not to the database,
  so the cache can live on a faster disk than the photos and still resolve them.
* Raw metadata lives in its own table: a screen of statistics is a dozen scans of
  ``photos``, and carrying a JSON blob per row made every one of those scans
  read pages it never looked at.
* One connection per thread; SQLite objects are not shared across threads.
* Every phase of a scan commits rows *and* its cursor in the same transaction, so
  an interrupted scan resumes exactly where it stopped.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from urllib.parse import quote

SCHEMA_VERSION = 4

#: Page cache per connection, and how much of the file SQLite may memory-map.
#: The read path runs a dozen index scans per screen; with the defaults a
#: 538k-photo library took 2.1s per refresh and 0.9s with these.
READ_CACHE_KIB = 64 * 1024
READ_MMAP_BYTES = 256 * 1024 * 1024

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
    orientation_tag INTEGER
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

-- The metadata exiftool returned for this photo, as JSON. Split out of photos
-- in schema v4: it is 25% of the file and no query on the statistics path ever
-- reads it, but every table scan used to walk over its pages.
CREATE TABLE IF NOT EXISTS photo_raw (
    photo_id INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    raw_json TEXT
);

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

#: The values ``build_photo_row`` returns, in order. ``raw_json`` is part of that
#: tuple but not a column of ``photos`` since schema v4 — see
#: :func:`split_photo_row`.
_PHOTO_COLUMN_NAMES = (
    "rel_path", "mod_time", "size", "taken_at", "date_source", "year", "month", "day",
    "camera", "camera_key", "lens", "lens_key", "iso", "shutter_seconds", "fnumber",
    "focal_mm", "focal35_mm", "flash_fired", "flash_raw", "white_balance", "file_type",
    "width", "height", "megapixels", "resolution", "raw_json", "orientation_tag",
)
PHOTO_COLUMNS = ", ".join(_PHOTO_COLUMN_NAMES)
_RAW_INDEX = _PHOTO_COLUMN_NAMES.index("raw_json")
_PHOTO_TABLE_NAMES = tuple(name for name in _PHOTO_COLUMN_NAMES if name != "raw_json")
_PHOTO_TABLE_COLUMNS = ", ".join(_PHOTO_TABLE_NAMES)

#: Statements built from that tuple so that the schema and the writes can never
#: drift apart. ``build_photo_row`` returns one value per name in
#: :data:`PHOTO_COLUMNS`; :func:`split_photo_row` takes the raw JSON out before
#: it reaches the insert.
PHOTO_INSERT_SQL = (
    f"INSERT INTO photos ({_PHOTO_TABLE_COLUMNS}) "
    f"VALUES ({','.join('?' * len(_PHOTO_TABLE_NAMES))})"
)
PHOTO_UPDATE_SQL = (
    "UPDATE photos SET "
    + ", ".join(f"{name} = ?" for name in _PHOTO_TABLE_NAMES[1:])
    + " WHERE id = ?"
)

RAW_INSERT_SQL = (
    "INSERT INTO photo_raw (photo_id, raw_json) VALUES (?, ?) "
    "ON CONFLICT(photo_id) DO UPDATE SET raw_json = excluded.raw_json"
)


def split_photo_row(row) -> tuple[tuple, str | None]:
    """Separate a :func:`build_photo_row` tuple into (photos values, raw JSON).

    The raw metadata goes to ``photo_raw`` in the same transaction as the row
    itself, so a photo is never left with half its metadata written.
    """
    values = tuple(value for index, value in enumerate(row) if index != _RAW_INDEX)
    return values, row[_RAW_INDEX]


def store_raw_json(conn: sqlite3.Connection, photo_id: int, raw_json: str | None) -> None:
    """Write (or clear) one photo's raw metadata, inside the caller's transaction."""
    if raw_json is None:
        conn.execute("DELETE FROM photo_raw WHERE photo_id = ?", (photo_id,))
    else:
        conn.execute(RAW_INSERT_SQL, (photo_id, raw_json))


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
        _tune_reads(conn)
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


def _tune_reads(conn: sqlite3.Connection) -> None:
    """Pragmas for the read path, where the defaults are wasteful.

    ``mmap_size`` is the one that counts: one screen runs a dozen scans over the
    same indexes, and mapping the file keeps those pages out of the read() path.
    On a 538k-photo library a full refresh went from 2.1s to 0.9s. Each pragma
    is suppressed on its own because a filesystem without mmap support (some
    network shares) must not make the cache unreadable.
    """
    for statement in (
        f"PRAGMA mmap_size = {READ_MMAP_BYTES}",
        f"PRAGMA cache_size = -{READ_CACHE_KIB}",
        "PRAGMA temp_store = MEMORY",
        "PRAGMA query_only = ON",
    ):
        with contextlib.suppress(sqlite3.Error):
            conn.execute(statement)


def root_folder(db_path: Path | str) -> str | None:
    """The library a cache was scanned from, or None if it cannot be read.

    Used to notice that a cache found in a shared folder belongs to a different
    library before it is opened and its rows pruned.
    """
    try:
        conn = connect(db_path, readonly=True)
    except sqlite3.Error:
        return None
    try:
        return get_meta(conn, "root_folder")
    except sqlite3.Error:
        return None
    finally:
        conn.close()


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
    # One `if version < N:` block per migration, oldest first.
    if version < 3:
        # Orientation (portrait/landscape) needs the EXIF Orientation tag. The
        # column is added for databases that predate it, and then filled from
        # the raw metadata already on every row — the tag was in raw_json all
        # along, so this costs a JSON parse and no file is opened. Rows whose
        # raw_json predates the tag stay NULL and fall back to the dimensions;
        # only re-reading those files can recover the rotation.
        _add_column(conn, "photos", "orientation_tag", "INTEGER")
        _backfill_orientation(conn)
    if version < 4:
        _split_raw_json(conn)
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                 (str(SCHEMA_VERSION),))


def _split_raw_json(conn: sqlite3.Connection) -> None:
    """Move ``raw_json`` out of ``photos`` into its own table (schema v4).

    On a 538k-photo library the column held 129 MB of JSON inside the table that
    every facet query scans; in a side table it still reads back per photo, but
    the hot table is a quarter smaller. The file is not VACUUM'd here — dropping
    the column frees its pages and the next writes reuse them, and compacting a
    cache that lives on a slow external drive would freeze the window for
    minutes. ``Move the cache…`` compacts with VACUUM INTO when the user asks.

    Idempotent: a migration interrupted after the copy finds no column and stops.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS photo_raw ("
        "photo_id INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE, "
        "raw_json TEXT)"
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(photos)")}
    if "raw_json" not in columns:
        return
    # One statement, so the copy lands whole or not at all.
    conn.execute(
        "INSERT OR REPLACE INTO photo_raw (photo_id, raw_json) "
        "SELECT id, raw_json FROM photos WHERE raw_json IS NOT NULL"
    )
    conn.execute("ALTER TABLE photos DROP COLUMN raw_json")
    # VACUUM is not housekeeping here, it is half the migration: DROP COLUMN
    # rewrites the table and leaves a file 25% larger, over which the refresh
    # measured 2.2s against 1.0s compacted on 538k photos. VACUUM is atomic, so
    # an interrupted one simply repeats on the next open. A second process
    # holding the cache can refuse the exclusive lock it wants; that must not
    # stop the app from opening a cache that is already usable (Move the cache…
    # compacts it later).
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("VACUUM")


def _backfill_orientation(conn: sqlite3.Connection) -> None:
    """Fill ``orientation_tag`` from the raw metadata already stored.

    A SQL UPDATE rather than a rescan: the tag is inside ``raw_json``, so there
    is nothing to read from disk. Guarded by ``json_valid`` because a malformed
    blob would otherwise abort the whole migration, and by ``IS NOT NULL`` so a
    row that never carried the tag is left for the dimension fallback.
    """
    conn.execute(
        "UPDATE photos SET orientation_tag = "
        "CAST(json_extract(raw_json, '$.Orientation') AS INTEGER) "
        "WHERE orientation_tag IS NULL AND json_valid(raw_json) "
        "AND json_extract(raw_json, '$.Orientation') IS NOT NULL"
    )


def _add_column(conn: sqlite3.Connection, table: str, column: str, kind: str) -> None:
    """ALTER TABLE ... ADD COLUMN, but only if it is not already there.

    ``CREATE TABLE IF NOT EXISTS`` is a no-op on an existing table, so a new
    column reaches only databases created from scratch. This is how it reaches
    the ones already on disk. Idempotent, because a half-applied migration must
    not make the next open fail.
    """
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
