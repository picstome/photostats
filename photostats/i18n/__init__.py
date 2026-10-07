"""Translations for the interface.

A tiny catalogue rather than a dependency: the app ships in two languages, and a
missing key must be obvious in testing instead of silently rendering empty.

Usage::

    tr("nav.scan")

Keys are the English source text, so an untranslated string is still readable
and ``python -m photostats --audit-translations`` lists what is missing.
"""

from __future__ import annotations

import json
import sys
from functools import cache
from pathlib import Path

#: Bundled languages, keyed by the code stored in settings.
LANGUAGES: dict[str, str] = {
    "en": "English",
    "es": "Espanol",
}

_DEFAULT = "en"
_active = _DEFAULT


class _Missing(str):
    """A key with no translation.

    Subclasses ``str`` so it can go straight into a Qt label showing the
    English key, while still being identifiable as untranslated by an audit or
    a test.
    """

    def __new__(cls, key: str) -> _Missing:
        value = super().__new__(cls, key)
        value.key = key
        return value

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"MissingTranslation({self.key!r})"


def catalogue_path(language: str) -> Path:
    return Path(__file__).with_name(f"{language}.json")


@cache
def load(language: str) -> dict[str, str]:
    """Read one catalogue, treating a missing file as empty."""
    path = catalogue_path(language)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def available() -> list[str]:
    return sorted(languages())


def languages() -> dict[str, str]:
    """Bundled languages that actually have a catalogue on disk."""
    found = {code: name for code, name in LANGUAGES.items() if catalogue_path(code).exists()}
    return found or dict(LANGUAGES)


def active() -> str:
    return _active


def set_language(language: str | None) -> str:
    """Switch language. ``None`` or an unknown code falls back to English."""
    global _active
    valid = language if language and language in languages() else _DEFAULT
    _active = valid
    return _active


def tr(key: str, **placeholders: object) -> str:
    """Translate ``key``, filling ``{placeholders}``."""
    catalogue = load(_active)
    if key not in catalogue:
        # Not a crash: an untranslated string still has to reach the screen.
        return _Missing(key) if _active != _DEFAULT else key
    template = catalogue[key]
    if not placeholders:
        return template
    try:
        return template.format(**placeholders)
    except (KeyError, IndexError, ValueError):
        # A malformed translation must not take the window down with it.
        return template


#: Locales Qt reports that mean Spanish, in the forms it reports them.
SPANISH_LOCALES = ("es", "es_ES", "es_ES.UTF-8", "es_MX", "es_AR", "es_CO",
                   "es_CL", "es_ES_419", "es_UY", "es_VE", "es_PE", "es_BO",
                   "es_DO", "es_GT", "es_HN", "es_NI", "es_PA", "es_PY", "es_PR",
                   "es_SV", "es_CR", "es_CA")


def system_language() -> str | None:
    """The language the OS asks for, if it is one we ship."""
    from PySide6.QtCore import QLocale

    code = QLocale.system().name().replace("-", "_")
    if code.lower().startswith("es"):
        return "es"
    return None


def choose_language(configured: str | None = None) -> str:
    """Resolve the language to use: the setting, else the OS, else English."""
    if configured:
        return configured
    return system_language() or _DEFAULT


def product_title(suffix_key: str | None = None) -> str:
    """The window title: 'Photo Stats by Picstome.com'.

    Translatable because the whole interface is — the attribution reads
    differently in English and Spanish. *suffix_key* is a catalogue key, not
    finished text, so 'Settings' arrives already translated.
    """
    from .. import AUTHOR

    title = tr("Photo Stats by {author}", author=AUTHOR)
    return f"{title} — {tr(suffix_key)}" if suffix_key else title


def missing_keys(language: str) -> list[str]:
    """Keys present in English but not translated into ``language``."""
    if language == _DEFAULT:
        return []
    english = load(_DEFAULT)
    target = load(language)
    return sorted(key for key in english if key not in target)


def audit() -> int:
    """Report untranslated keys per language; returns the total missing."""
    total = 0
    for language in languages():
        if language == _DEFAULT:
            continue
        gaps = missing_keys(language)
        total += len(gaps)
        for key in gaps:
            print(f"{language}: {key}")
    print(f"{total} untranslated string(s)")
    return total


if __name__ == "__main__":  # pragma: no cover - manual tool
    sys.exit(1 if audit() else 0)
