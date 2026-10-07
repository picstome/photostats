"""Stored preferences, the shipped defaults, and resetting to them."""

from __future__ import annotations

import pytest

from photostats.core.config import AppConfig
from photostats.core.indexer import DEFAULT_BATCH, DEFAULT_WORKERS
from photostats.core.paths import CACHE_NEXT_TO_PHOTOS, Paths


@pytest.fixture
def config(tmp_path) -> AppConfig:
    """A config on its own ini file, so no other test's writes are visible."""
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    return AppConfig(settings=settings, paths=Paths(app_data_dir=tmp_path / "data"))


def test_defaults_match_the_benchmarked_values():
    """The defaults are the measured optimum, not a round guess."""
    assert DEFAULT_WORKERS >= 2
    assert DEFAULT_WORKERS <= 12
    # 50 was the fastest column and the smoothest; 1200 measured 40% slower.
    assert DEFAULT_BATCH == 50


def test_worker_default_leaves_cores_for_the_interface():
    import os

    cores = os.cpu_count() or 4
    # Two cores back so the window stays responsive during a scan.
    assert max(2, cores - 1) >= DEFAULT_WORKERS


def test_a_fresh_install_reads_the_shipped_defaults(config):
    assert config.theme_name == "system"
    assert config.cache_mode == CACHE_NEXT_TO_PHOTOS
    assert config.workers == DEFAULT_WORKERS
    assert config.batch_size == DEFAULT_BATCH
    assert config.include_no_date is False
    assert config.language == ""          # empty means follow the system


def test_settings_round_trip(config):
    config.set_theme("dark")
    config.set_indexing(3, 500)
    config.set_include_no_date(True)
    config.set_language("es")

    assert config.theme_name == "dark"
    assert config.workers == 3
    assert config.batch_size == 500
    assert config.include_no_date is True
    assert config.language == "es"


def test_clearing_the_language_returns_to_the_system_default(config):
    config.set_language("es")
    config.set_language("")
    assert config.language == ""


def test_updates_are_on_by_default_and_can_be_turned_off(config):
    from datetime import datetime

    assert config.updates_enabled is True
    assert config.last_update_check is None

    config.set_updates_enabled(False)
    assert config.updates_enabled is False

    when = datetime(2026, 10, 7, 9, 30)
    config.set_last_update_check(when)
    assert config.last_update_check == when


def test_reset_defaults_turns_updates_back_on(config):
    config.set_updates_enabled(False)
    config.set_last_update_check()

    config.reset_defaults()

    assert config.updates_enabled is True
    assert config.last_update_check is None


def test_reset_defaults_undoes_every_stored_preference(config):
    config.set_theme("dark")
    config.set_indexing(1, 4000)
    config.set_include_no_date(True)
    config.set_language("es")
    config.set_exiftool_path("/usr/local/bin/exiftool")

    config.reset_defaults()

    assert config.theme_name == "system"
    assert config.cache_mode == CACHE_NEXT_TO_PHOTOS
    assert config.workers == DEFAULT_WORKERS
    assert config.batch_size == DEFAULT_BATCH
    assert config.include_no_date is False
    assert config.language == ""
    assert config.exiftool_path == ""


def test_reset_defaults_survives_a_reload(tmp_path):
    from PySide6.QtCore import QSettings

    ini = str(tmp_path / "settings.ini")
    paths = Paths(app_data_dir=tmp_path / "data")
    first = AppConfig(settings=QSettings(ini, QSettings.IniFormat), paths=paths)
    first.set_theme("light")
    first.set_indexing(2, 300)
    first.set_language("es")
    first.sync()

    second = AppConfig(settings=QSettings(ini, QSettings.IniFormat), paths=paths)
    assert second.theme_name == "light"

    second.reset_defaults()
    third = AppConfig(settings=QSettings(ini, QSettings.IniFormat), paths=paths)
    assert third.theme_name == "system"
    assert third.workers == DEFAULT_WORKERS
    assert third.language == ""


# -- folders that have gone away -------------------------------------------

def test_a_remembered_folder_that_no_longer_exists_is_forgotten(config):
    config.set_library("/tmp/photostats-no-such-folder/photos")
    assert config.settings.value("library")
    assert config.library == ""
    assert not config.settings.contains("library")


def test_a_remembered_folder_that_still_exists_is_kept(config, tmp_path):
    real = tmp_path / "photos"
    real.mkdir()
    config.set_library(real)
    assert config.library == str(real)


def test_recent_folders_that_have_gone_are_pruned(config, tmp_path):
    real = tmp_path / "photos"
    real.mkdir()
    config.add_recent(str(real))
    config.add_recent("/tmp/photostats-no-such-folder")
    config.forget_missing()
    assert config.recents == [str(real)]


def test_forget_missing_reports_what_it_dropped(config):
    config.settings.setValue("library", "/tmp/photostats-no-such-folder")
    config.settings.setValue("recents", ["/tmp/photostats-no-such-folder"])
    forgotten = config.forget_missing()
    assert forgotten == ["/tmp/photostats-no-such-folder"]


def test_forget_missing_leaves_a_live_library_alone(config, tmp_path):
    real = tmp_path / "photos"
    real.mkdir()
    config.set_library(real)
    assert config.forget_missing() == []
    assert config.library == str(real)
