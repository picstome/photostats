# Photo Stats

**Photo Stats** is a desktop app for photographers who want to know what they
actually shoot: which body, which lens, how often the flash fires, what ISO and
aperture they default to. Point it at a folder of photos and it reads the EXIF
metadata of every RAW and JPEG, then lets you slice the result by date, camera,
lens, aperture, shutter speed, ISO, focal length, flash, white balance and file
type.

Everything runs on your machine. No account, no upload, no cloud.

![Photo Stats](docs/screenshot.png)

---

## Install

Download the build for your platform from
[the releases page](https://github.com/neo22s/photostats/releases).

| Platform | File |
|---|---|
| macOS (Apple silicon) | `Photo Stats-arm64.dmg` |
| macOS (Intel) | `Photo Stats-x64.dmg` |
| Windows | `PhotoStats-windows.zip`, or `PhotoStats-Setup.exe` for an installer |
| Linux | `PhotoStats-linux.tar.gz` |

### exiftool

Photo Stats uses [exiftool](https://exiftool.org) to read metadata, and needs it
installed once:

```bash
# macOS
brew install exiftool

# Linux (Debian/Ubuntu)
sudo apt install libimage-exiftool-perl

# Linux (Fedora)
sudo dnf install perl-Image-ExifTool

# Windows: download exiftool.exe from exiftool.org and put it in your PATH
```

If Photo Stats cannot find it, a setup sheet appears with the exact command for
your system. You can also point it at a specific file in **Settings → exiftool →
Locate…**, which is useful with a portable exiftool on a USB stick.

> **macOS:** the build is ad-hoc signed, so the first launch shows "cannot be
> opened because it is from an unidentified developer". Right-click the app →
> **Open** → **Open** once; afterwards it launches normally.

---

## Use it

1. **Open** a photo folder (`Browse…`, or drag the folder onto the window).
2. Photo Stats writes `photo_stats.db` inside that folder and scans it. New
   photos are added on the next scan; nothing else is re-read.
3. Click any bar in a chart to filter. Click it again to release the filter.
   Every chart updates live, showing what *would* happen if you made a different
   choice — that is what makes it feel like one instrument rather than eight
   reports.

### The window

One page, top to bottom, with the filters on the left:

```
┌───────────────────────────────────────────────────────────────────────┐
│ YOUR PHOTO STATS                                                      │
│ Pictures                                                    [Open] [Scan] │
│ /Users/you/Pictures                                                   │
├──────────────┬────────────────────────────────────────────────────────┤
│ Filters      │  18,402 photos shown │ 1 library │ 12 cameras │ 2019–2025│
│              │  [60%] Nikon Z8  [50%] 24-70mm  [24] busiest month     │
│ Cameras      ├────────────────────────────────────────────────────────┤
│ ☐ NIKON Z8   │  Timeline — drag to select a period                     │
│ ☐ Canon R6   ├────────────────────────────────────────────────────────┤
│ Lenses       │  Cameras      │  Lenses       │  ISO                    │
│ ISO      ▭▭  │  ▇▇▇▇▇▇▇ 72  │  ▇▇▇▇▇▇ 60   │  ▇▇▇▇▇▇ 12               │
│ Shutter  ▭▭  │  Aperture     │  Shutter      │  Focal length           │
│ Aperture ▭▭  │                                                            │
│ Focal    ▭▭  │                            [ Show 1,204 photos ]      │
└──────────────┴────────────────────────────────────────────────────────┘
```

The page opens with its conclusion: the four figures and the insight sentences
that read them sit together at the top, then the timeline, then the charts.

**The scan is always announced.** The line under the toolbar reports what the app
is doing at all times — files found, how far through the metadata it is, the rate
and the time remaining — and the Scan button becomes Stop. Nothing is ever hidden
behind a panel you might not notice.

**A long scan steps forward.** If a scan is still running after half a second, a
dialog appears with a determinate bar and the same figures:

```
Reading photo details
▓▓▓▓▓▓░░░░░░░░░░░░░░░
750 of 3,060 photos · 25%
3,060 new · 1,050/s · about 2s left
                              [ Continue in background ]  [ Stop ]
```

It is deliberately **not** modal. **Continue in background** gets it out of the
way and leaves the header reporting progress, so a scan never blocks using the
app. A rescan of an already-indexed library finishes in milliseconds and shows
no dialog at all — the header just says *Index up to date*.

**Nothing scrolls unless it has to.** The page fits a 1440×900 window without a
scrollbar; on a shorter one the timeline and the charts scroll together as one
column (so every box keeps the same width), and the sidebar lists cap their own
height so one long list cannot push everything else off screen.

**The photo list is a button.** A grid of every file was taking half the window
for something most sessions never look at. Now the main window ends with
**Show 1,204 photos**, which opens the list in its own window — sortable,
paged, with double-click to reveal in Finder.

### Filters

**Cameras** starts open — it is the facet a photographer reaches for first.
Everything else in the sidebar starts collapsed, because eight open panels is a
wall and you use two or three. Click a heading to open one.

- **Cameras, lenses** — searchable lists with live counts and share bars. Click
  anywhere on a row to filter by it; click again to remove it. Several at once
  is fine.
- **ISO, shutter, aperture, focal length** — drag either handle; double-click to
  reset; arrow keys for fine adjustment.
- **Flash** — fired / not fired.
- **Date** — click either field to pop a calendar, or use `This year` /
  `12 months` / `30 days` / `All`. The fields rest on the oldest photo in the
  library and on today — never a year in the future — and only filter once you
  move inside that span.
  Last, because it is the filter you reach for least.
- **Timeline** — drag across the histogram to select a period.

Each active filter appears as a chip above the charts; click a chip to remove it.

Opening a library always starts with nothing filtered. A slider spanning its
whole range is no filter, not a filter that happens to match everything, so a
fresh library shows no chips and no "active" count.

The header says what the page is about: an eyebrow reading **Your photo stats**
over the library's name as the title, with the path underneath to check it
against. A bare folder name on its own read as a label with nothing above it.

**Open** is both the folder picker and the recent list, since they are the same
intent. The settings and theme buttons carry drawn icons rather than Unicode
characters, which rendered as emoji or as empty boxes depending on the
platform's font fallback.

The camera and lens lists keep their own search boxes, which do work: they
narrow a long list of bodies or glass. There is no free-text search box in the
top bar — it was never wired to anything, and the timer behind it never stopped.

The individual files are there when you want them, and out of the way when you
do not.

#### The sliders show your library, not a textbook

The handles span the values actually in your photos: the lowest ISO anyone shot
and the highest. On a library of 100–3,200 ISO the track reads `100 – 3 200`,
not `50 – 204,800`, so the whole width is meaningful and the reset is exact.
The numbers are written the way a photographer writes them — `1/500 – 0.5s`,
`f/1.8 – f/8`, `24mm – 200mm`, and ISO as a plain number.

#### Charts say what you pressed

Clicking a bar filters by it. A pill appears on the card naming exactly what is
selected, with the count when you pick more than one:

```
Cameras                            NIKON Z8 +1  ×
```

Click the pill to clear that one filter. A silent highlight is easy to miss, and
it is worse not knowing *which* value is now driving every other chart.

Each bar shows its count and its share — `1,055 · 94%` — so a facet reads at a
glance without doing the arithmetic.

**Charts cross-filter; the numbers above them describe the selection.** Pick a
camera and its chart still shows every body (with the share each one would have),
because you need the alternatives to switch between them — but the tiles, the
insights and the exports speak for the photos on screen. A sentence is skipped
rather than quoted against the wrong total when its own facet is what you
filtered by.

### Languages

English and Spanish, chosen in **Settings → Language**. With nothing chosen the
app follows the operating system. Text, button labels, column headings, month
names, the insights and the photo-list window all switch together.

To check for gaps between the catalogues:

```bash
python -m photostats --audit-translations
```

It prints every string that has no Spanish equivalent and exits non-zero if
there are any, so an untranslated label cannot quietly ship. That check runs in
the test suite too.

### Branding

The interface uses the Picstome house palette, and both themes are built from the
five brand colours rather than from a generic accent:

| | | |
|---|---|---|
| Pine Blue | `#316D61` | primary: charts, selection, focus |
| Graphite | `#322F30` | dark surfaces, and text on light |
| Vibrant Coral | `#EE6958` | the one thing you press: Scan, Stop |
| Tea Green | `#C6D8AF` | soft fills: chips, the insights row |
| Floral White | `#FFF9EC` | light surfaces, and text on dark |

Every other tone is mixed from those five in `photostats/ui/theme.py`, so adding
a shade cannot drift away from the brand. Pine is carried at a lighter tint on
the dark theme, because `#316D61` does not read as a colour against a dark
surface. Text contrast is asserted in the test suite at the WCAG AA ratio.

Typeface is **League Spartan**, with a system fallback stack so the app still
looks right on a machine where the font is not installed. The stack is built at
runtime from the fonts actually installed — naming a missing one makes Qt print a
font-alias warning on every launch. The font and the logo
files go in `photostats/assets/` — see the README there. Neither is required:
with the folder empty the app falls back to the system font and a mark drawn in
pine blue.

### Settings

**Settings → Language** offers *Match the system* first, which is the default:
with nothing chosen the app follows the operating system, so a Spanish macOS
gives you a Spanish interface without anyone touching a switch.

**Restore defaults** puts every field back to its shipped value — theme, cache
location, exiftool path, language, and the two indexing numbers below. You can
still press Cancel afterwards; the buttons only move the widgets until you press
Save.

#### Making a big scan as fast as possible

Two settings matter. One of them matters about twenty times more than the other.

**Read files in parallel** — this is the whole story. Reading EXIF is per-process
CPU work inside exiftool's Perl runtime, so it parallelises almost perfectly.

**Batch size** — worth about 5% between 50 and 250, and worth avoiding entirely
above that.

Measured on 4,000 files, 10-core machine, five interleaved runs per cell so the
machine drifting under the benchmark cannot favour one setting. Files per second:

| parallel | batch 50 | batch 100 | batch 250 | batch 1200 |
|---|---|---|---|---|
| **1** | 552 | 555 | 558 | 555 |
| **4** | 1,060 | 1,062 | 1,064 | 952 |
| **8** | 1,496 | 1,395 | 1,389 | 943 |
| **12** | 1,616 | 1,447 | 1,353 | 919 |

Read across a row and the parallel setting is close to linear — **2.7x from one
worker to eight**. Read down the right-hand column and the batch setting looks
irrelevant until it does not: 1,200 is 40% slower than 50, because every worker
spends longer idle waiting for a full batch to collect.

So the defaults are:

- **Read files in parallel: `cores − 2`, capped at 12.** Two cores stay free for
  the window and the database, which is what keeps the app usable mid-scan.
  On a 4-core laptop that is 2; on 10 cores it is 8. Twelve was the fastest
  single cell above, but by only ~8%, and it lost to eight at the larger batch
  sizes, so the default stays at or below the core count.
- **Batch size: 50.** The fastest column, and the smoothest — the progress bar
  advances every fifty photos rather than every thousand.

Two honest caveats. These numbers come from a warm page cache on a fast SSD with
small JPEGs. Real RAW files shift the bottleneck towards disk I/O, where extra
parallel reads help much less and the batch size matters even less — so raise
the parallel setting first, then re-measure on your own library and your own
drive. And on a laptop, 4 is a kinder default than 8 if the fan noise bothers
you.

### Shortcuts

| | |
|---|---|
| `Ctrl/Cmd+O` | Open a folder |
| `Ctrl/Cmd+R` | Rescan |
| `Ctrl/Cmd+,` | Settings |
| `Ctrl/Cmd+Shift+L` | Toggle dark / light |
| `Esc` | Clear all filters |
| `Ctrl/Cmd+Backspace` | Clear all filters |
| `Esc` | Close the photo list window |

Double-click a row in the photo list to reveal the photo in Finder or Explorer.

### Export

There is no export button in the window. The same three writers are on the
command line, where you can pipe them:

```bash
photostats-cli ~/Pictures --csv photos.csv      # the matching photos, one row each
photostats-cli ~/Pictures --json report.json    # filters, full statistics, photos
photostats-cli ~/Pictures --text                # a readable report
```

---

### RAW and JPEG of the same shot count once

A camera writes two files for one photograph — a RAW and a JPEG. Photo Stats
counts the photograph, not the files.

When a folder holds `IMG_0001.DNG` and `IMG_0001.JPG`, that is **one photo**,
and the metadata comes from the **RAW**. The RAW carries the full EXIF; a JPEG
written by the camera often has a fraction of it. The JPEG is not recorded at
all, so it cannot be mistaken for a second photograph and nothing double-counts
on screen or in an export.

So a folder with six RAW+JPEG pairs — twelve files — reports six photos, with
the bodies, lenses and exposure from the RAWs.

Rules that follow:

The JPEG of a pair is **never opened**. It is not counted, not recorded, and
never handed to exiftool — the loser of a group is discarded during the walk,
before anything reads metadata. (Tested by putting a deliberately corrupt JPEG
next to a valid RAW: the scan completes with no error at all.)

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

## Where the data lives

`photo_stats.db` is a normal SQLite database stored **inside your photo folder**.
Two consequences worth knowing:

- **It travels with your library.** Copy the folder to another computer, open it,
  and Photo Stats shows the cached statistics immediately, then reads only the
  photos that machine does not have yet.
- **It is inspectable.** Open it with any SQLite tool — DB Browser for SQLite,
  the `sqlite3` command line, DuckDB, pandas — and query the `photos` table
  directly. The schema is documented in [docs/schema.md](docs/schema.md).

Paths are stored **relative** to the folder, which is what makes the database
portable. A clean shutdown merges the write-ahead log into the file, so the single
`.db` is self-contained; there is nothing else to copy.

Read-only drives and network shares cannot hold the database (SQLite needs
locking). Photo Stats detects this and keeps the cache on your computer instead;
**Settings → Statistics cache** controls where it goes.

Deleting `photo_stats.db` is always safe: it just means the next scan reads the
metadata again.

### Coming from the original script

If you used the earlier `photo_stats.py`, Photo Stats offers to import its
`photo_stats_cache.db` the first time you open that folder. It converts the text
values (`1/125`, `f/2.8`, `50 mm`) into real numbers and links them to the files,
so a first scan that would have taken hours takes seconds. The old file is only
read, never modified.

---

## Command line

The original script is gone, but its report is still one command away:

```bash
photostats-cli ~/Pictures --stats
```

```
Photo Stats
========================================
48,213 photos

=== Cameras ===
NIKON Z8: 21,404 (44.4%)
Canon EOS R6: 12,880 (26.7%)
…
```

Filters and exports:

```bash
photostats-cli ~/Pictures --camera "NIKON Z8" --iso-min 400 --iso-max 3200 --stats
photostats-cli ~/Pictures --csv photos.csv
photostats-cli ~/Pictures --json report.json
photostats-cli ~/Pictures --no-scan          # use the cache only
photostats-cli ~/Photos --import-legacy       # import an old cache and stop
```

---

## From source

```bash
git clone https://github.com/neo22s/photostats.git
cd photostats
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m photostats                          # run the app
```

Run the tests and linter:

```bash
QT_QPA_PLATFORM=offscreen pytest -q
ruff check photostats tests
```

Build a distributable bundle (each platform builds on its own runner):

```bash
pyinstaller build/photostats.spec --noconfirm
```

Release builds come from `.github/workflows/build.yml`: tests run once, then
macOS arm64, macOS x64, Windows and Linux are built in parallel and attached to
a GitHub release. Push a `v*` tag to cut one.

**The bundle identifier is `com.picstome.photostats`**, set in
`build/photostats.spec`. When you sign, the certificate has to match it.

---

## How it works

See [docs/how-it-works.md](docs/how-it-works.md) for a brief technical overview.

---

## Credits

Developed by **[Picstome.com](https://picstome.com)** — a collection of free,
open-source tools for photographers.

Released under the MIT licence.

### Third-party software

| Software | Licence | Used for |
|---|---|---|
| [exiftool](https://exiftool.org) | Perl Artistic / GPL | Reading EXIF metadata from every photo |
| [PySide6](https://www.qt.io) | LGPL-3.0 | The Qt GUI framework |
| [PyInstaller](https://pyinstaller.org) | GPL-2.0 (with exception) | Packaging the app into a standalone bundle |
| [ruff](https://docs.astral.sh/ruff) | MIT | Linting |
| [pytest](https://docs.pytest.org) | MIT | Test framework |
| [League Spartan](https://www.theleagueofmoveabletype.com) | SIL OFL 1.1 | Typeface (optional, not bundled) |
