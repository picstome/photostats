# How it works

A brief technical overview of Photo Stats.

## Architecture

```
photostats/
├── core/            no Qt — testable on its own, and usable from the CLI
│   ├── paths.py     where the cache and logs live
│   ├── db.py        schema, connections, migrations
│   ├── formats.py   RAW/JPEG/TIFF/HEIC support and grouping priority
│   ├── parse.py     exiftool JSON → normalised columns
│   ├── exiftool.py  persistent `exiftool -stay_open` driver
│   ├── scanner.py   phase A: walk, group duplicates, diff the cache
│   ├── indexer.py   phase B: read metadata in parallel, resumable
│   ├── legacy.py    import a cache from the original script
│   ├── filters.py   the filter model and its SQL
│   ├── queries.py   cross-filtered facets, timeline, results
│   ├── insights.py  the sentences above the charts
│   └── export.py    CSV / JSON / text
└── ui/              PySide6 widgets; nothing here touches SQLite directly
    ├── main_window.py    page layout, queries, wiring
    └── panels/           folder list window, scan status, filters, charts, tiles
```

## Two key decisions

**Paths are relative.** `photos.rel_path` is stored relative to the folder holding
the database, so a library can be moved or copied anywhere and still open.

**Scanning is resumable.** A scan has two phases. The walk persists the list of
directories it still has to visit; the metadata reader commits its rows and the
extraction cursor in the same transaction. Interrupt it at any point — crash,
Ctrl-C, power loss — and the next scan continues from the last committed batch,
with no duplicates and no gaps.

## Performance

For speed, one persistent `exiftool -stay_open` process per worker is reused for
the whole scan instead of starting a new one per batch, and every statistic is an
indexed SQL `GROUP BY` run on a background thread. Each result carries a
generation number, so a filter change made while queries are running discards the
stale result instead of flickering.

Measured on 101,000 photos, for a full refresh of all eight charts, the timeline,
the totals and the first page of the table:

| Interaction | Time |
|---|---|
| Dragging a slider (sidebar lists unchanged) | ~0.7–0.9 s |
| Changing a camera / lens / date (lists refetched) | ~0.9–1.1 s |

That is the time to redraw everything, not the time to respond: the window stays
interactive throughout and shows the previous result until the new one is ready.
On a library of a few thousand photos — the usual case — a refresh is around
15 ms. If you need faster on very large libraries, the next step would be
materialised aggregate tables rather than live `GROUP BY`.

> One exiftool quirk worth knowing, because it bites everyone writing a wrapper:
> in `-stay_open` mode, passing `-q` makes exiftool suppress the `{ready}` marker
> that tells you a command finished, and the reader blocks forever. The driver in
> `core/exiftool.py` refuses `-q` for exactly this reason.

## Reading exif data is I/O work

On a library on an external drive, nearly all the time in a first scan is the
drive delivering the file, not exiftool parsing it. Two things follow, and both
are measured rather than assumed.

**`-fast` (exiftool level 1) is worth about 1.7×, and costs nothing.** It stops
exiftool scanning past the end of the image for trailing data it does not use.
The faster levels are not free: `-fast2` also skips EXIF MakerNotes, which is
where several bodies keep the lens model — it loses `Lens` and `LensType` on
JPEGs — and above that whole tags disappear.
`tests/test_indexing.py::test_the_fast_flag_costs_no_tags` pins flag to tag set
so a later "just try `-fast5`" cannot quietly empty the lens chart.

**More workers help only until they thrash the drive.** `workers × batch` is the
number of files being read at once, and a drive has a ceiling well below what a
fast cores count suggests: on the 9 TB exFAT volume this app was tuned against,
16 workers × 250 files made every batch time out and the scan read nothing. The
reader therefore measures its own failures and shrinks the batch for the rest of
the scan (a fifth, floor ten), which recovers that case automatically instead of
timing out forever. `Settings → Read files in parallel` still matters most.

**The time left follows the disk now, not the whole run.** The rate used to be
files divided by seconds since the scan began, so it was anchored to the walk —
a phase measured in directories per second that takes minutes on a large library
and was counted in the same total — and it never reacted when the drive sped up
or slowed down. It is now a rolling window of the last 15 seconds, falling back
to the phase and then the whole run until there is history to measure.

## Cross-filtering, and what the numbers describe

A facet is queried with **every filter except its own** — `Filter.to_sql(omit=…)`.
That is what lets a chart keep offering alternatives: with `NIKON Z8` selected,
the camera chart still shows the Canon and Sony bars, each with the share it
would have if you switched. Those counts describe the library, not the current
selection.

Everything that *speaks for the selection* therefore has to stay out of that
scope:

- **Tiles and insights** — a tile or a sentence that divides a facet count by
  the matched total must use facets computed with all filters applied, or it
  reports nonsense (`1,055 / 26` reads as `4058%`). `Insights._facet` returns
  nothing for a facet the user has already narrowed, because there is no true
  sentence to write about it.
- **Exports** — a report headed "24 photos" lists the selection's cameras, not
  the library's, so `export.py` asks for scoped facets (`omit_self=False`).
- **Charts and the sidebar lists** — deliberately cross-filtered; their counts
  and shares are internally consistent with each other.

`PhotoStore.facet(name, filters, omit_self=False)` is the scoped query, and
`Filter.facet_active(name)` is the check for "would omitting this facet change
the clause?" — pinned against `to_sql` in `tests/test_filters.py` so the two
cannot drift apart.

## RAW + JPEG grouping

A camera writes two files for one photograph — a RAW and a JPEG. Photo Stats
counts the photograph, not the files.

When a folder holds `IMG_0001.DNG` and `IMG_0001.JPG`, that is **one photo**,
and the metadata comes from the **RAW**. The RAW carries the full EXIF; a JPEG
written by the camera often has a fraction of it. The JPEG is not recorded at
all, so it cannot be mistaken for a second photograph and nothing double-counts
on screen or in an export.

Precedence, highest first: **RAW → TIFF / HEIC → PNG / JPEG**.

- **Extension case does not matter.** `IMG_0001.dng` and `IMG_0001.jpg` group.
- **Different file names are different photos.** `IMG_0001.DNG` and
  `IMG_0001_edited.JPG` count as two, because they are.
- **Never merge two genuinely different shots**, even when the names match.
- **Grouping is per folder.** A RAW in `raw/` and its JPEG in `jpeg/` count as
  two. Matching on name alone across the whole library would be worse, because
  cameras reuse `IMG_0001` every day and it would merge different shots and lose
  photos. Matching across folders safely needs capture time as well, which is a
  larger change to the walk.

## The database

`photo_stats.db` is a plain SQLite file, written inside the photo folder. Anything
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
the file travel between machines. A clean shutdown merges the write-ahead log
into the file, so the single `.db` is self-contained; there is nothing else to
copy.

Read-only drives and network shares cannot hold the database (SQLite needs
locking). Photo Stats detects this and keeps the cache on your computer instead;
**Settings → Statistics cache** controls where it goes.

Deleting `photo_stats.db` is always safe: it just means the next scan reads the
metadata again.

See [schema.md](schema.md) for the full table layout.

## Updates

Photo Stats asks the GitHub Releases API **at most once a month** for the latest
tag and compares it, as a tuple of ints, with `__version__`. When it is newer the
window shows a banner whose **Download** button opens the asset built for the
running platform (the archive's file names are matched by `asset_name()`), or the
release page if the release carries none.

The rules that keep it quiet and cheap:

- the gap is stored in the app settings as an ISO timestamp, and written *before*
  the request — so a machine that is offline at check time waits the full month
  rather than retrying on every launch;
- every failure is silent: no network, a rate limit, unexpected JSON or a missing
  field all return `None`, because being offline is not an error worth a dialog;
- one `GET`, no token, no telemetry, and it can be turned off in Settings.

## Resilience

The app is used on libraries that are large, on external drives, and full of
files no tool can read. A few rules follow from that, each one learned the hard
way:

- **One bad file costs one file.** `build_photo_row` is called inside a guard in
  `Indexer._write_batch`; a value the parser cannot handle is counted, logged and
  skipped instead of killing the batch.
- **A failing batch is halved, not retried.** `Indexer._read_with` splits a batch
  on failure, down to single files, so a slow drive or one unreadable file loses
  one photo rather than 250.
- **The read batch adapts to the drive.** When a batch times out, the size asked
  for subsequent batches drops (a fifth, floor 10). A library on a slow USB drive
  used to time out on every single batch, because `workers × batch` files in
  flight is more than the drive can serve.
- **Nothing is built off the main thread.** The crash reporter logs on a worker
  thread and only opens a dialog on the GUI thread, because macOS aborts on a
  window created anywhere else. Work threads catch broadly and always emit a
  result, so a failure reaches the window instead of leaving it on
  "Importing…" forever.
- **exiftool's stderr is drained as it goes.** Nothing reads it until something
  fails, and exiftool writes one line per unreadable file — on a library with
  thousands of those, the queue used to grow for the whole scan.
- **Cleaners accept non-strings.** exiftool sometimes returns a number for a
  field that is normally text; the regex-based cleaners coerce with `str()`
  before matching.

## Tests

```bash
QT_QPA_PLATFORM=offscreen pytest -q     # all platforms, headless
```

The suite is deliberately ordinary — no display, no network, no real library:

- `tests/conftest.py` builds a synthetic library by stamping EXIF onto a 1×1
  JPEG with exiftool, so the tests exercise the same code path as a real scan
  without needing photographs.
- `tests/test_ui.py` drives the real `MainWindow` offscreen: opening a library,
  filtering, the scan lifecycle, the charts, the calendar, the update banner.
- `tests/test_indexing.py` covers caching, crash/resume and the resilience rules
  — including that a scan survives a file whose parse fails.
- `tests/test_filters.py` pins `facet_active()` to `to_sql()`'s `omit` behaviour,
  which is what keeps a share from ever being computed against the wrong total.
- `tests/test_updates.py` replaces `urllib` with a fake response, so the update
  check is tested without a network.
- `tests/test_indexing.py` also guards the release artefacts: the icons exist,
  the spec bundles the translation catalogues (a build without them showed the
  raw key — the window title read `Photo Stats by {author}`).

## Changing the schema

Bump `SCHEMA_VERSION` in `core/db.py` and add a forward migration block to
`_migrate()`. Every stored row is written in the same transaction as the progress
that got it there, so an interrupted scan resumes rather than double-counting.

A migration is not always the answer, though. **Orientation** — portrait,
landscape, other — is a `CASE` rather than a stored classification, because it
is a pure function of data already on the row. It does need one thing a cache
indexed by an older version does not have: the EXIF **Orientation** tag. A camera
writes the sensor's dimensions and records the rotation separately, so a portrait
frame is stored 6960×4640 with Orientation 8 — and comparing width with height
alone counted almost every portrait shot as landscape. Tags 5–8 mean a quarter
turn, so the displayed dimensions are the stored ones swapped.

So this one *did* need a schema change: `SCHEMA_VERSION` is 3 and `_migrate()`
adds an `orientation_tag` column with `ALTER TABLE` (a `CREATE TABLE IF NOT
EXISTS` never reaches a table that already exists).

Crucially, filling it for a cache that already exists does **not** need a rescan.
The full exiftool record is stored per row in `raw_json`, and the tag is inside
it, so the migration backfills with one SQL statement — `json_extract(raw_json,
'$.Orientation')` — opening no files at all. On a half-million-row cache that is
about two seconds; the same work as a re-read would be hours on an external
drive, because the cost of a rescan is the drive, not exiftool.

Only rows whose `raw_json` predates the tag (a cache written by a build older
than this one) keep it NULL and fall back to the dimensions. There is no cheaper
recovery for those: an orientation-only exiftool pass measures barely faster than
a full read — the file still has to be opened — so it would be a rescan by
another name. For those, `photostats-cli --refresh` re-reads every photo.

A normal scan will *not* fix a cache like that, and that surprises people. The
walk only reads files whose size or modification time changed, so re-scanning an
untouched library reads nothing — it finishes in a second and the stale rows stay
stale. `--refresh` is the deliberate exception: it unlinks every photo from its
file (without deleting the photo, so the window keeps showing numbers) and lets
the ordinary scan re-read them. Because "unlinked but the photo is still there"
is exactly the state the scan treats as "not read yet", a refresh **resumes**
after a stop like any other scan — run the same command again and it carries on
instead of starting over. `--reindex` is the blunter option: it deletes the cache
and rebuilds, which is what you want after corruption, not for filling a field.

The rule of thumb: a stored column earns a migration when it is filtered and
indexed often, and a derived expression is right when it is a pure function of
data already present — but "already present" has to include the tags the scan
actually read.
