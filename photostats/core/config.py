"""Settings: theme, cache location, exiftool path, recent folders.

Everything lives in QSettings so the app remembers how you left it. Kept apart
from the engine so that the core can be used without a GUI.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from .. import APP_NAME, ORG_NAME
from .paths import CACHE_NEXT_TO_PHOTOS, Paths

MAX_RECENTS = 8


class AppConfig:
    """Thin typed wrapper around QSettings."""

    def __init__(self, settings: QSettings | None = None, paths: Paths | None = None) -> None:
        self.settings = settings or QSettings(ORG_NAME, APP_NAME)
        self.paths = paths or Paths()

    # -- theme -------------------------------------------------------------
    @property
    def theme_name(self) -> str:
        return self.settings.value("theme", "system")

    def set_theme(self, name: str) -> None:
        self.settings.setValue("theme", name)

    def resolve_theme(self, system_is_dark: bool) -> str:
        name = self.theme_name
        if name == "system":
            return "dark" if system_is_dark else "light"
        return name if name in ("dark", "light") else "dark"

    # -- library -----------------------------------------------------------
    @property
    def library(self) -> str:
        """The remembered library, or "" when it is not there any more.

        Folders go away: an external drive is unplugged, a folder is renamed,
        a temporary directory is cleaned out. Returning a path that no longer
        exists would make the app open to an error instead of asking which
        folder to use, so a dead path is forgotten the moment it is noticed.
        """
        stored = str(self.settings.value("library", "") or "")
        if not stored or Path(stored).expanduser().is_dir():
            return stored
        self.forget_missing()
        return ""

    def set_library(self, folder: Path | str | None) -> None:
        if folder is None:
            self.settings.remove("library")
            self._forget_recent(str(folder))
            return
        folder = str(folder)
        self.settings.setValue("library", folder)
        self.add_recent(folder)

    @property
    def recents(self) -> list[str]:
        raw = self.settings.value("recents", []) or []
        if isinstance(raw, str):
            raw = [raw]
        return [str(item) for item in raw if str(item)]

    def forget_missing(self) -> list[str]:
        """Drop any remembered library and recent folder that has gone.

        Returns what was forgotten, so the caller can mention it if it needs to.
        """
        forgotten: list[str] = []
        stored = str(self.settings.value("library", "") or "")
        if stored and not Path(stored).expanduser().is_dir():
            self.settings.remove("library")
            forgotten.append(stored)
        recents = self.recents
        kept = [item for item in recents if Path(item).expanduser().is_dir()]
        if len(kept) != len(recents):
            self.settings.setValue("recents", kept)
        # Reported once each: the same folder is usually both the library and a
        # recent, and a caller saying so twice is noise.
        for item in recents:
            if item not in kept and item not in forgotten:
                forgotten.append(item)
        return forgotten

    def add_recent(self, folder: str) -> None:
        recents = [item for item in self.recents if item != folder]
        recents.insert(0, folder)
        self.settings.setValue("recents", recents[:MAX_RECENTS])

    def _forget_recent(self, folder: str | None) -> None:
        if folder:
            self.settings.setValue(
                "recents", [item for item in self.recents if item != str(folder)]
            )

    # -- cache -------------------------------------------------------------
    @property
    def cache_mode(self) -> str:
        return self.settings.value("cache_mode", CACHE_NEXT_TO_PHOTOS)

    @property
    def cache_custom_path(self) -> str:
        return str(self.settings.value("cache_custom", ""))

    def db_path(self, folder: Path | str | None) -> Path:
        custom = self.cache_custom_path or None
        return self.paths.db_path(
            Path(folder) if folder else None, self.cache_mode, Path(custom) if custom else None
        )

    @property
    def cache_is_portable(self) -> bool:
        return self.cache_mode == CACHE_NEXT_TO_PHOTOS

    def set_cache(self, mode: str, custom: str = "") -> None:
        self.settings.setValue("cache_mode", mode)
        if custom:
            self.settings.setValue("cache_custom", custom)

    # -- exiftool ----------------------------------------------------------
    @property
    def exiftool_path(self) -> str:
        return str(self.settings.value("exiftool_path", ""))

    def set_exiftool_path(self, path: Path | str | None) -> None:
        if path:
            self.settings.setValue("exiftool_path", str(path))
        else:
            self.settings.remove("exiftool_path")

    # -- indexing ----------------------------------------------------------
    @property
    def workers(self) -> int:
        """exiftool processes to run; 0 means "choose from the CPU count"."""
        from .indexer import DEFAULT_WORKERS

        return int(self.settings.value("workers", 0) or 0) or DEFAULT_WORKERS

    @property
    def batch_size(self) -> int:
        from .indexer import DEFAULT_BATCH

        return int(self.settings.value("batch_size", DEFAULT_BATCH))

    def set_indexing(self, workers: int | None, batch_size: int) -> None:
        if workers:
            self.settings.setValue("workers", workers)
        self.settings.setValue("batch_size", batch_size)

    @property
    def include_no_date(self) -> bool:
        return bool(self.settings.value("include_no_date", False, type=bool))

    def set_include_no_date(self, value: bool) -> None:
        self.settings.setValue("include_no_date", value)

    # -- language ----------------------------------------------------------
    @property
    def language(self) -> str:
        """The UI language; empty means "follow the system"."""
        return str(self.settings.value("language", "") or "")

    def set_language(self, language: str | None) -> None:
        if language:
            self.settings.setValue("language", language)
        else:
            self.settings.remove("language")

    def reset_defaults(self) -> None:
        """Forget every stored preference and fall back to the built-in ones.

        Used by the Settings dialog's "Restore defaults", which has to be able
        to clear keys it does not otherwise read, such as a language override.
        """
        from .indexer import DEFAULT_BATCH, DEFAULT_WORKERS
        from .paths import CACHE_NEXT_TO_PHOTOS

        self.settings.setValue("theme", "system")
        self.settings.setValue("cache_mode", CACHE_NEXT_TO_PHOTOS)
        self.settings.remove("cache_custom_path")
        self.settings.remove("exiftool_path")
        self.settings.setValue("workers", DEFAULT_WORKERS)
        self.settings.setValue("batch_size", DEFAULT_BATCH)
        self.settings.setValue("include_no_date", False)
        self.settings.remove("language")
        self.settings.sync()

    def sync(self) -> None:
        self.settings.sync()
