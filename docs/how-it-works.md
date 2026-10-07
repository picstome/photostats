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
