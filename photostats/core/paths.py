"""Filesystem locations: where the cache database and logs live.

The database normally sits inside the scanned photo folder so it travels with it,
but that is not always possible (read-only mounts, network shares) — and even
when it is, the photos may live on a slow drive while the machine has a fast one.
So there are three places it can go:

* next to the photos, which keeps the pair portable;
* the per-user application data directory;
* a folder the user chooses, typically an internal SSD.

The two latter are shared by every library, so each gets its own subfolder:
without it, opening a second library would reuse the first one's cache, prune
its rows and force a full rescan.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import unicodedata
from pathlib import Path

from .. import APP_SLUG

DB_FILENAME = "photo_stats.db"
LEGACY_DB_FILENAME = "photo_stats_cache.db"

#: Cache location choices exposed in Settings.
CACHE_NEXT_TO_PHOTOS = "next_to_photos"
CACHE_LOCAL = "local"
CACHE_CUSTOM = "custom"

_UNC_PREFIXES = ("\\\\", "//")

#: Characters a library folder name may keep in its cache folder. Spaces and
#: anything exotic become dashes; the hash beside it keeps the name unique.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def library_key(folder: Path | str) -> str:
    """A stable folder name for one library's cache, e.g. ``Photoshop-1a2b3c4d``.

    Readable enough to tell two libraries apart in a folder listing, with a hash
    of the resolved path so two folders with the same name never collide.
    """
    path = Path(os.path.realpath(os.path.expanduser(str(folder))))
    # Fold the accents rather than turn them into dashes: "Otoño" reads better
    # as "Otono" than as "Oto-o" in a folder listing.
    name = unicodedata.normalize("NFKD", path.name)
    name = "".join(char for char in name if not unicodedata.combining(char))
    name = _SAFE_NAME.sub("-", name)
    name = re.sub(r"-{2,}", "-", name).strip("-._") or "library"
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:8]
    return f"{name[:40]}-{digest}"


def same_folder(first: Path | str, second: Path | str) -> bool:
    """True when two paths name the same directory, symlinks and case aside.

    macOS and Windows resolve a folder case-insensitively, so ``/Volumes/Photos``
    and ``/volumes/photos`` are the same library even though the strings differ.
    """
    def key(value: Path | str) -> str:
        text = os.path.realpath(os.path.expanduser(str(value)))
        return text.casefold() if sys.platform in ("darwin", "win32") else text

    return key(first) == key(second)


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

    def cache_root(self, mode: str = CACHE_NEXT_TO_PHOTOS,
                   custom: Path | None = None) -> Path | None:
        """The folder that holds caches, or None when they live with the photos."""
        if mode == CACHE_CUSTOM:
            if custom:
                root = Path(custom).expanduser()
                if root.is_absolute():
                    return root
            # A relative or placeholder value — an older build could save the
            # dialog's "—" as the chosen folder — would put the cache in the
            # process's working directory. Fall back rather than write there.
            return self.app_data_dir
        if mode == CACHE_LOCAL:
            return self.app_data_dir
        return None

    def db_path(self, photo_folder: Path | None, mode: str = CACHE_NEXT_TO_PHOTOS,
                custom: Path | None = None) -> Path:
        """Return the database path for a photo folder under the given mode."""
        root = self.cache_root(mode, custom)
        if root is None:
            if photo_folder:
                return Path(photo_folder) / DB_FILENAME
            return self.app_data_dir / DB_FILENAME
        if photo_folder:
            return root / library_key(photo_folder) / DB_FILENAME
        return root / DB_FILENAME

    def legacy_db_path(self, mode: str = CACHE_NEXT_TO_PHOTOS,
                       custom: Path | None = None) -> Path | None:
        """Where builds before a per-library folder put the cache.

        One fixed file for every library. Still looked for first, so a cache
        someone already moved into a chosen folder is adopted instead of being
        rebuilt from scratch.
        """
        root = self.cache_root(mode, custom)
        return root / DB_FILENAME if root is not None else None
