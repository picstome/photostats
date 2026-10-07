"""End-to-end indexing tests: caching, incremental updates, crash-resume."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from conftest import make_library

from photostats.core.db import connect, init_db
from photostats.core.indexer import PHASE_DONE, PHASE_PAUSED, Indexer


def scan(db: Path, root: Path, **kwargs):
    return Indexer(db, root, **kwargs).run()


def counts(db: Path, sql: str) -> list[tuple]:
    conn = connect(db, readonly=True)
    try:
        return [tuple(row) for row in conn.execute(sql)]
    finally:
        conn.close()


@pytest.fixture
def indexed(tmp_path):
    """A freshly indexed 24-photo library (8 of them with a RAW companion)."""
    root = tmp_path / "photos"
    make_library(root, count=24)
    db = root / "photo_stats.db"
    init_db(db)
    result = scan(db, root)
    assert result.ok
    return root, db, result


def test_first_scan_indexes_one_row_per_shot(indexed):
    root, db, result = indexed
    # 24 shots on disk, 8 of them also present as a .cr2 companion.
    assert counts(db, "SELECT COUNT(*) FROM photos") == [(24,)]
    assert result.extracted == 24
    assert result.stats.new == 24
    assert result.stats.cached == 0


def test_raw_wins_over_jpeg_when_grouping(indexed):
    root, db, _ = indexed
    # Only the winner of each group is stored, so the .cr2 replaces the .jpg.
    assert counts(db, "SELECT rel_path, is_raw FROM files WHERE base_name = 'IMG_4000'") == [
        ("IMG_4000.cr2", 1)
    ]
    assert counts(db, "SELECT file_type FROM photos WHERE rel_path = 'IMG_4000.cr2'") == [("raw",)]
    assert counts(db, "SELECT COUNT(*) FROM photos WHERE rel_path = 'IMG_4000.jpg'") == [(0,)]


def test_metadata_is_parsed_into_numeric_columns(indexed):
    root, db, _ = indexed
    # IMG_4000 is the first fixture photo: ISO 100, 1/500s, f/1.8, 24mm, flash fired.
    row = counts(db, "SELECT iso, shutter_seconds, fnumber, focal_mm, flash_fired, year "
                     "FROM photos WHERE rel_path = 'IMG_4000.cr2'")
    assert row == [(100, 0.002, 1.8, 24.0, 1, 2024)]


def test_rescan_is_fully_cached_but_still_walks(indexed):
    root, db, _ = indexed
    result = scan(db, root)
    assert result.ok
    assert result.extracted == 0
    assert result.stats.cached == 24
    assert result.stats.new == 0
    # A rescan must still visit the tree, otherwise changes would go unnoticed.
    assert result.stats.directories == 5


def test_added_and_deleted_files_are_picked_up(indexed):
    root, db, _ = indexed
    make_library(root / "2024" / "julio", count=6, with_pairs=False)
    (root / "2024" / "mayo" / "IMG_4001.jpg").unlink()  # index 1: no RAW companion

    result = scan(db, root)
    assert result.stats.new == 6
    assert result.stats.removed == 1
    assert counts(db, "SELECT COUNT(*) FROM photos") == [(29,)]


def test_changed_file_is_re_read(indexed):
    root, db, _ = indexed
    target = root / "2024" / "junio" / "IMG_4002.jpg"
    target.write_bytes(target.read_bytes() + b"\x00")  # size change, new mtime
    result = scan(db, root)
    assert result.stats.updated == 1
    assert result.extracted == 1
    assert counts(db, "SELECT COUNT(*) FROM photos") == [(24,)]


def test_removed_folder_is_pruned(indexed):
    root, db, _ = indexed
    before = counts(db, "SELECT COUNT(*) FROM photos")[0][0]
    shutil.rmtree(root / "vacaciones")
    result = scan(db, root)
    assert result.stats.removed > 0
    after = counts(db, "SELECT COUNT(*) FROM photos")[0][0]
    assert after < before
    assert counts(db, "SELECT COUNT(*) FROM files WHERE rel_dir = 'vacaciones'") == [(0,)]


def test_moved_file_is_reindexed_with_a_new_rel_path(indexed):
    """Grouping is per directory, so a shot moved elsewhere is one new path."""
    root, db, _ = indexed
    destination = root / "2024" / "junio"
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("IMG_4000.cr2", "IMG_4000.jpg"):
        shutil.move(str(root / name), str(destination / name))
    result = scan(db, root)
    assert result.stats.new == 1
    assert result.stats.removed == 1
    # The shot is still counted once, now under its new path.
    assert counts(db, "SELECT COUNT(*) FROM photos") == [(24,)]
    assert counts(db, "SELECT rel_path FROM photos WHERE rel_path LIKE '%IMG_4000%'") == [
        ("2024/junio/IMG_4000.cr2",)
    ]


def test_cancel_midway_then_resume(tmp_path):
    """An interrupted scan must continue: no duplicates, nothing skipped."""
    root = tmp_path / "photos"
    make_library(root, count=40, with_pairs=False)
    db = root / "photo_stats.db"
    init_db(db)

    indexer = Indexer(db, root, batch=10, workers=1)
    original_write = indexer._write_batch
    batches = {"count": 0}

    def stop_after_two(conn_arg, rows):
        batches["count"] += 1
        if batches["count"] > 2:
            indexer.cancel()
        return original_write(conn_arg, rows)

    indexer._write_batch = stop_after_two
    paused = indexer.run()

    assert paused.paused
    assert paused.ok is False
    assert counts(db, "SELECT phase FROM scan_state")[0][0] == PHASE_PAUSED
    partial = counts(db, "SELECT COUNT(*) FROM photos")[0][0]
    assert 0 < partial < 40, f"expected a partial index, got {partial}"
    assert counts(db, "SELECT COUNT(*) FROM (SELECT rel_path FROM photos "
                       "GROUP BY rel_path HAVING COUNT(*) > 1)") == [(0,)]

    resumed = scan(db, root, batch=10, workers=1)
    assert resumed.ok
    assert counts(db, "SELECT COUNT(*) FROM photos") == [(40,)]
    assert counts(db, "SELECT phase FROM scan_state")[0][0] == PHASE_DONE
    # Only the photos that had not been written yet were read again.
    assert resumed.extracted == 40 - partial


def test_cancel_before_start_does_not_short_circuit(tmp_path):
    root = tmp_path / "photos"
    make_library(root, count=6, with_pairs=False)
    db = root / "photo_stats.db"
    init_db(db)
    indexer = Indexer(db, root)
    indexer.cancel()
    result = indexer.run()  # run() clears a stale cancel
    assert result.ok
    assert result.photos == 6


def test_empty_folder_produces_an_empty_index(tmp_path, empty_folder):
    db = empty_folder / "photo_stats.db"
    init_db(db)
    result = scan(db, empty_folder)
    assert result.ok
    assert result.photos == 0
    assert result.summary == "0 photos"


def test_unicode_and_spaces_in_paths(tmp_path):
    root = tmp_path / "fotos de viaje"
    folder = root / "Ärbol 東京"
    folder.mkdir(parents=True)

    from conftest import TINY_JPEG

    from photostats.core.exiftool import ExifTool, find_exiftool

    paths: list[Path] = []
    for index, name in enumerate(("viaje ñ 1.jpg", "bä japan.jpg")):  # noqa: B007
        path = folder / name
        path.write_bytes(TINY_JPEG)
        paths.append(path)
    with ExifTool(find_exiftool()) as tool:
        for index, path in enumerate(paths):
            tool.execute([
                "-overwrite_original", f"-Model=Cam {index}", f"-ISO={100 * (index + 1)}", str(path)
            ])
    db = root / "photo_stats.db"
    init_db(db)
    result = scan(db, root)
    assert result.ok
    assert result.photos == 2
    rel = {row[0] for row in counts(db, "SELECT rel_path FROM photos")}
    assert rel == {"Ärbol 東京/viaje ñ 1.jpg", "Ärbol 東京/bä japan.jpg"}


# -- release artefacts ------------------------------------------------------
# The workflow once looked for the bundle at dist/Photo Stats/Photo Stats.app,
# which PyInstaller never creates, so every macOS release failed at its first
# line. These check the paths the workflow and the spec actually agree on.

def test_the_icon_files_for_every_platform_exist():
    """macOS wants .icns, Windows wants .ico, and will not fall back to .png."""
    from pathlib import Path

    assets = Path(__file__).resolve().parents[1] / "build" / "assets"
    for name in ("icon.icns", "icon.ico", "icon.png"):
        assert (assets / name).is_file(), f"{name} is missing"
        assert (assets / name).stat().st_size > 512


def test_the_windows_icon_is_a_real_ico():
    import struct
    from pathlib import Path

    data = (Path(__file__).resolve().parents[1] / "build" / "assets" / "icon.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0 and kind == 1, "not an icon container"
    assert count >= 4, "too few sizes; Windows needs at least 16/32/48/256"
    sizes = [data[6 + 16 * i] or 256 for i in range(count)]
    assert 16 in sizes and 32 in sizes and 256 in sizes


def test_the_spec_ships_the_translation_catalogues():
    """A build without them shows raw keys everywhere.

    The 1.0 bundle was built before the package was installed, so
    ``collect_data_files`` found nothing and every ``tr()`` fell back to its
    key — the window title read "Photo Stats by {author}". The spec now reads
    the catalogues straight from the tree; this guards that.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = (root / "build" / "photostats.spec").read_text()
    assert "photostats/i18n" in spec, "the spec no longer bundles the catalogues"
    for code in ("en", "es"):
        assert (root / "photostats" / "i18n" / f"{code}.json").is_file()


def test_the_windows_installer_says_picstome():
    from pathlib import Path

    script = (Path(__file__).resolve().parents[1] / "build" / "photostats.iss").read_text()
    assert 'AppPublisher "Picstome.com"' in script
    assert "picstome.com" in script
    assert "chemaphoto" not in script, "the installer still points at the old brand"
    assert "SetupIconFile" in script


def test_the_release_workflow_uses_the_path_pyinstaller_actually_writes():
    from pathlib import Path

    workflow = (Path(__file__).resolve().parents[1]
                / ".github" / "workflows" / "build.yml").read_text()
    # Comments are allowed to mention the wrong path to explain why it is wrong,
    # so only the runnable lines are checked.
    code = "\n".join(line for line in workflow.splitlines()
                     if not line.lstrip().startswith("#"))
    assert 'APP="dist/Photo Stats.app"' in code
    assert 'dist/Photo Stats/Photo Stats.app' not in code


def test_the_bundle_identifier_is_the_picstome_one():
    """It has to match the signing certificate, so it is pinned rather than free."""
    import re
    from pathlib import Path

    spec = (Path(__file__).resolve().parents[1] / "build" / "photostats.spec").read_text()
    match = re.search(r'bundle_identifier="([^"]+)"', spec)
    assert match, "no bundle identifier in the spec"
    assert match.group(1) == "com.picstome.photostats"
    # The README states it too; if either moves, the other must follow.
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert match.group(1) in readme


def test_a_failed_batch_is_split_rather_than_lost(tmp_path):
    """exiftool times out on a batch too big for the drive; don't lose all of it.

    On an external drive a 250-file batch across 16 workers can exceed the
    180s timeout, and one file exiftool cannot parse kills the process. The old
    reader retried the same batch and dropped every file in it — on a real
    library that was 84,000 photos with no metadata. Halving recurses down to
    single files, so the slow part still gets read and a bad file costs one.
    """
    from photostats.core.exiftool import ExifToolError
    from photostats.core.indexer import Indexer

    root = tmp_path / "photos"
    root.mkdir()
    indexer = Indexer(tmp_path / "photo_stats.db", root)

    class Flaky:
        """Fails on anything bigger than two files, like a timeout would."""

        def __init__(self) -> None:
            self.calls = 0

        def read_paths(self, files):
            self.calls += 1
            if len(files) > 2:
                raise ExifToolError("timed out")
            return [{"SourceFile": path} for path in files]

        def close(self) -> None:
            pass

    tool = Flaky()
    batch = [(index, f"IMG_{index:04d}.jpg") for index in range(7)]
    rows = indexer._read_with(tool, batch)

    assert len(rows) == 7
    assert tool.calls > 1, "the batch was not split"
    assert indexer._errors == 0


def test_a_slow_drive_shrinks_the_read_batch(tmp_path):
    """16 workers x 250 files overwhelms an external drive; it times out.

    The reader notices and asks for fewer files per batch for the rest of the
    scan, instead of timing out on every one and importing nothing.
    """
    from photostats.core.exiftool import ExifToolError
    from photostats.core.indexer import Indexer

    root = tmp_path / "photos"
    root.mkdir()
    indexer = Indexer(tmp_path / "photo_stats.db", root, workers=16, batch=250)

    class AlwaysTimesOut:
        def read_paths(self, files):
            raise ExifToolError("exiftool timed out after 180s")

        def close(self) -> None:
            pass

    batch = [(index, f"IMG_{index:04d}.jpg") for index in range(250)]
    indexer._read_with(AlwaysTimesOut(), batch)

    assert indexer._effective_batch == 50  # 250 // 5, the size that works
