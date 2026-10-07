# The `photo_stats.db` schema

The database is a plain SQLite file, written inside the photo folder. Anything
that can read SQLite can read it — DB Browser for SQLite, the `sqlite3`
command line, DuckDB, pandas, R.

```bash
sqlite3 ~/Pictures/photo_stats.db "SELECT camera, COUNT(*) FROM photos GROUP BY camera"
```

```python
import sqlite3, pandas
conn = sqlite3.connect("~/Pictures/photo_stats.db")
df = pd.read_sql("SELECT * FROM photos WHERE iso >= 3200", conn)
```

Paths are **relative to the folder containing the database**, which is what lets
the file travel between machines.

---

## `photos`

One row per shot, so it is the table to query.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | Primary key |
| `rel_path` | TEXT | **Unique.** Relative, POSIX separators, e.g. `2024/mayo/IMG_4821.CR2` |
| `mod_time` | REAL | Unix timestamp, for detecting changed files |
| `size` | INTEGER | Bytes |
| `taken_at` | TEXT | `'YYYY-MM-DD HH:MM:SS'`, local time, from `DateTimeOriginal` |
| `date_source` | TEXT | `exif`, `mtime` (fell back to the file date), or `none` |
| `year`, `month`, `day` | INTEGER | Split out so grouping by month is a single index |
| `camera`, `camera_key` | TEXT | Display name and its normalised key |
| `lens`, `lens_key` | TEXT | Same |
| `iso` | INTEGER | Lowest ISO of a bracketed burst |
| `shutter_seconds` | REAL | `1/500` is stored as `0.002` |
| `fnumber` | REAL | `f/2.8` → `2.8` |
| `focal_mm`, `focal35_mm` | REAL | `24 mm` → `24.0`; the 35mm equivalent separately |
| `flash_fired` | INTEGER | `1`, `0`, or `NULL` when the camera did not say |
| `flash_raw` | TEXT | The original string, e.g. `Off, Did not fire` |
| `white_balance` | TEXT | Normalised: `auto`, `manual`, `daylight`, `cloudy`, `fluorescent`, `tungsten`, `shade`, `flash` |
| `file_type` | TEXT | `raw`, `jpeg`, `tiff` |
| `width`, `height`, `megapixels` | INTEGER/REAL | Resolution |
| `raw_json` | TEXT | The untouched exiftool record, so new tags can be added without a re-scan |

`camera_key` / `lens_key` are lower-cased and whitespace-collapsed. They are what
the app filters on, so `NIKON Z8` and `nikon  z8` are one selection.

### Querying it

```sql
-- Cameras in order of use
SELECT camera, COUNT(*) AS photos
FROM photos GROUP BY camera ORDER BY photos DESC;

-- A month of telephoto work
SELECT taken_at, camera, fnumber, focal_mm
FROM photos
WHERE year = 2024 AND month = 6 AND focal_mm >= 200
ORDER BY taken_at;

-- Share of each aperture
SELECT fnumber, ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM photos), 1) AS pct
FROM photos WHERE fnumber IS NOT NULL GROUP BY fnumber ORDER BY fnumber;

-- Photos per month
SELECT year, month, COUNT(*) FROM photos GROUP BY year, month ORDER BY year, month;

-- Pairings that only happen once
SELECT camera, lens, COUNT(*) AS n FROM photos
GROUP BY camera, lens HAVING n <= 2;
```

---

## `files`

The scan record: one row per file it decided to keep. Only the winner of each
`dir + base name` group is stored, so `IMG_4821.CR2` alongside `IMG_4821.JPG`
leaves a single row (the RAW wins).

| Column | Notes |
|---|---|
| `id`, `rel_path` (`UNIQUE`) | The file |
| `rel_dir`, `base_name` | Grouping key |
| `ext`, `is_raw` | Extension and whether it is RAW |
| `mod_time`, `size` | Compared on the next scan to spot changes |
| `representative` | `1` for the file whose metadata was read |
| `photo_id` | Links to `photos.id`; `NULL` means "metadata not read yet" |

**`photo_id IS NULL` is the resume mechanism.** A row is linked to its photo in
the same transaction that writes that photo, so an interrupted scan can never
skip or duplicate a file.

```sql
-- Files whose metadata is still missing (a scan was interrupted, or failed)
SELECT rel_path FROM files WHERE photo_id IS NULL;

-- Orphaned rows, should always be empty
SELECT COUNT(*) FROM files WHERE representative = 1 AND photo_id IS NULL;
```

---

## `dirs`

Every directory the last walk visited, so that folders deleted since the previous
scan can be pruned from the statistics.

## `scan_state`

A single row (`id = 1`) holding the scan's cursor:

| Column | Notes |
|---|---|
| `phase` | `idle`, `walk`, `extract`, `done`, `paused` |
| `walk_stack` | JSON list of directories still to visit — a paused walk continues here |
| `partial_dir` | Directory being visited |
| `extract_cursor` | Highest `files.id` written; informational |
| `total_files`, `new_count`, `cached_count`, `updated_count`, `error_count` | Progress counters |

## `meta`

Key/value: `schema_version`, `root_folder`, `root_scanned_at`, and
`legacy_imported_from` when a cache from the original script was imported.

---

## Versioning

`meta.schema_version` records the schema the file was written with; Photo Stats
migrates older files forward automatically. Read it if you script against the
database:

```sql
SELECT value FROM meta WHERE key = 'schema_version';
```

## Maintenance

Safe at any time:

```bash
# Compact after deleting a big folder (the app does this on a clean exit too)
sqlite3 ~/Pictures/photo_stats.db "VACUUM;"

# Start over: the next scan re-reads every photo
rm ~/Pictures/photo_stats.db
```

`photo_stats.db-wal` and `-shm` exist only while the app is running. Closing it
merges them into the single `.db`, so copy just that one file.