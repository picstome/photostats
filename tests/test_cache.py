"""Which cache a library opens, and moving it to another disk without a rescan."""

from __future__ import annotations

import pytest

from photostats.core import db as dbmod
from photostats.core.cache import move, resolve
from photostats.core.config import AppConfig
from photostats.core.paths import CACHE_CUSTOM, DB_FILENAME, Paths


@pytest.fixture
def config(tmp_path) -> AppConfig:
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    return AppConfig(settings=settings, paths=Paths(app_data_dir=tmp_path / "app"))


def cache_at(path, root=None, photos: int = 1):
    """A small cache, optionally recording which library it came from."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dbmod.init_db(path)
    conn = dbmod.connect(path)
    try:
        if root is not None:
            dbmod.set_meta(conn, "root_folder", str(root))
        for index in range(photos):
            conn.execute("INSERT INTO photos (rel_path) VALUES (?)", (f"{index}.jpg",))
    finally:
        conn.close()
    return path


def test_the_per_library_file_is_preferred(config, tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    config.set_cache(CACHE_CUSTOM, str(tmp_path / "cache"))
    own = cache_at(config.db_path(photos))
    cache_at(config.legacy_db_path(), root=photos)

    assert resolve(config, photos).path == own


def test_a_cache_moved_by_hand_is_adopted_where_it_sits(config, tmp_path):
    """The upgrade path: the fixed file already holds the 500k-row index."""
    photos = tmp_path / "photos"
    photos.mkdir()
    config.set_cache(CACHE_CUSTOM, str(tmp_path / "cache"))
    legacy = cache_at(config.legacy_db_path(), root=photos)

    target = resolve(config, photos)

    assert target.path == legacy
    assert target.foreign_root is None
    assert not config.db_path(photos).exists(), "nothing is copied behind the user's back"


def test_a_cache_without_a_recorded_root_is_adopted_too(config, tmp_path):
    """Older builds did not write root_folder; refusing them would force a rescan."""
    photos = tmp_path / "photos"
    photos.mkdir()
    config.set_cache(CACHE_CUSTOM, str(tmp_path / "cache"))
    legacy = cache_at(config.legacy_db_path())

    assert resolve(config, photos).path == legacy


def test_a_library_copied_elsewhere_keeps_its_cache(config, tmp_path):
    """Copying the whole library is portable: the paths resolve, so adopt it."""
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (new / "a.jpg").write_bytes(b"not a real photo")
    config.set_cache(CACHE_CUSTOM, str(tmp_path / "cache"))
    legacy = cache_at(config.legacy_db_path(), root=old)
    conn = dbmod.connect(legacy)
    conn.execute(
        "INSERT INTO files (rel_path, rel_dir, base_name, ext) VALUES ('a.jpg', '', 'a', 'jpg')"
    )
    conn.close()

    target = resolve(config, new)

    assert target.path == legacy
    assert target.foreign_root is None


def test_a_cache_from_another_library_is_flagged_not_opened(config, tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    config.set_cache(CACHE_CUSTOM, str(tmp_path / "cache"))
    legacy = cache_at(config.legacy_db_path(), root=tmp_path / "somewhere-else")

    target = resolve(config, photos)

    assert target.path == config.db_path(photos)
    assert target.legacy == legacy
    assert target.foreign_root == str(tmp_path / "somewhere-else")


def test_next_to_the_photos_never_looks_elsewhere(config, tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    assert resolve(config, photos).path == photos / DB_FILENAME


def test_move_copies_every_photo_and_leaves_the_original(config, tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    config.set_cache(CACHE_CUSTOM, str(tmp_path / "cache"))
    source = cache_at(config.legacy_db_path(), root=photos, photos=7)
    target = config.db_path(photos)

    move(source, target)

    assert source.exists(), "the original is left alone until the user deletes it"
    assert target.exists()
    conn = dbmod.connect(target, readonly=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 7
        assert dbmod.get_meta(conn, "root_folder") == str(photos)
    finally:
        conn.close()


def test_move_refuses_to_overwrite_and_to_start_from_nothing(tmp_path):
    source = cache_at(tmp_path / "cache" / "photo_stats.db", photos=1)
    target = tmp_path / "cache" / "library" / "photo_stats.db"

    move(source, target)
    with pytest.raises(FileExistsError):
        move(source, target)
    with pytest.raises(FileNotFoundError):
        move(tmp_path / "nope.db", tmp_path / "other.db")
