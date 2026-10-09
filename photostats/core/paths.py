"""Filesystem locations: where the cache database and logs live.

The database normally sits inside the scanned photo folder so it travels with it,
but that is not always possible (read-only mounts, network shares), so we fall
back to the per-user application data directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .. import APP_SLUG

DB_FILENAME = "photo_stats.db"
LEGACY_DB_FILENAME = "photo_stats_cache.db"

#: Cache location choices exposed in Settings.
CACHE_NEXT_TO_PHOTOS = "next_to_photos"
CACHE_LOCAL = "local"
CACHE_CUSTOM = "custom"

_UNC_PREFIXES = ("\\\\", "//")


class Paths:
    """Resolve the directories Photo Stats reads and writes."""

    def __init__(self, app_data_dir: Path | None = None) -> None:
        self._app_data_dir = app_data_dir

    @property
    def app_data_dir(self) -> Path:
        """Per-user application data directory (created on demand)."""
        if self._app_data_dir is not None:
            path = Path(self._app_data_dir)
        elif sys.platform == "darwin":
            path = Path.home() / "Library" / "Application Support" / "Photo Stats"
        elif sys.platform == "win32":
            base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
            path = Path(base) / APP_SLUG
        else:
            base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
            path = Path(base) / APP_SLUG
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def config_dir(self) -> Path:
        """Directory for logs and other auxiliary files."""
        path = self.app_data_dir / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def log_file(self) -> Path:
        return self.config_dir / "photo_stats.log"

    def db_path(self, photo_folder: Path | None, mode: str = CACHE_NEXT_TO_PHOTOS,
                custom: Path | None = None) -> Path:
        """Return the database path for a photo folder under the given mode."""
        if mode == CACHE_CUSTOM and custom:
            custom = Path(custom)
            custom.parent.mkdir(parents=True, exist_ok=True)
            return custom / DB_FILENAME
        if mode == CACHE_LOCAL:
            return self.app_data_dir / DB_FILENAME
        if photo_folder:
            return Path(photo_folder) / DB_FILENAME
        return self.app_data_dir / DB_FILENAME
