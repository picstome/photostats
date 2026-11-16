"""Where the cache file goes, and how two libraries sharing a folder stay apart."""

from __future__ import annotations

import sys
from pathlib import Path

from photostats.core.paths import (
    CACHE_CUSTOM,
    CACHE_LOCAL,
    DB_FILENAME,
    Paths,
    library_key,
    same_folder,
)


def test_next_to_the_photos_keeps_the_old_behaviour(tmp_path):
    paths = Paths(app_data_dir=tmp_path / "app")
    photos = tmp_path / "photos"
    assert paths.db_path(photos) == photos / DB_FILENAME


def test_a_library_without_a_folder_falls_back_to_the_app_data_dir(tmp_path):
    paths = Paths(app_data_dir=tmp_path / "app")
    assert paths.db_path(None) == tmp_path / "app" / DB_FILENAME
    assert paths.legacy_db_path() is None


def test_local_caches_are_kept_apart_per_library(tmp_path):
    paths = Paths(app_data_dir=tmp_path / "app")
    first = tmp_path / "one"
    second = tmp_path / "two"

    first_db = paths.db_path(first, CACHE_LOCAL)
    second_db = paths.db_path(second, CACHE_LOCAL)

    assert first_db.parent.parent == tmp_path / "app"
    assert first_db.name == DB_FILENAME
    assert first_db != second_db
    assert first_db.parent.name == library_key(first)


def test_a_chosen_folder_gets_one_subfolder_per_library(tmp_path):
    paths = Paths(app_data_dir=tmp_path / "app")
    cache = tmp_path / "cache"
    photos = tmp_path / "Photoshop"

    db = paths.db_path(photos, CACHE_CUSTOM, cache)

    assert db == cache / library_key(photos) / DB_FILENAME
    # The fixed file older builds wrote is what the resolver looks for next.
    assert paths.legacy_db_path(CACHE_CUSTOM, cache) == cache / DB_FILENAME


def test_a_placeholder_folder_never_writes_the_cache_beside_the_process(tmp_path):
    """Older builds could save the dialog's "—" as the folder; never honour it."""
    paths = Paths(app_data_dir=tmp_path / "app")
    photos = tmp_path / "photos"

    db = paths.db_path(photos, CACHE_CUSTOM, Path("—"))

    assert db.parent.parent == tmp_path / "app"
    assert db.is_absolute()


def test_a_library_key_is_readable_stable_and_unique(tmp_path):
    one = tmp_path / "Leslie - Otoño 2026"
    two = tmp_path / "Leslie - Otoño 2027"

    key = library_key(one)
    assert key.startswith("Leslie-Oto")
    assert key == library_key("" + str(one)), "the same folder must key the same"
    assert key != library_key(two), "two folders with twin names must not collide"


def test_the_same_folder_spelled_differently_is_the_same_folder(tmp_path):
    photos = tmp_path / "Photos"
    photos.mkdir()

    assert same_folder(photos, photos)
    if sys.platform in ("darwin", "win32"):
        assert same_folder(photos, str(photos).upper())
    assert not same_folder(photos, tmp_path / "Other")
