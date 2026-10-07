"""The two bundled languages, and that the whole interface speaks them."""

from __future__ import annotations

import json

import pytest

from photostats import i18n


@pytest.fixture(autouse=True)
def restore_language():
    """Every test starts and ends in English so ordering cannot matter."""
    previous = i18n.active()
    yield
    i18n.set_language(previous)


def test_both_languages_are_offered():
    assert set(i18n.languages()) == {"en", "es"}


def test_english_is_the_fallback_for_an_unknown_code():
    i18n.set_language("fr")
    assert i18n.active() == "en"
    i18n.set_language(None)
    assert i18n.active() == "en"


def test_translating_switches_language():
    i18n.set_language("en")
    assert i18n.tr("Scan") == "Scan"
    i18n.set_language("es")
    assert i18n.tr("Scan") == "Analizar"


def test_spanish_is_not_a_copy_of_english():
    i18n.set_language("es")
    assert i18n.tr("Filters") == "Filtros"


#: Words that genuinely are the same in Spanish, so a copy is not a bug.
SAME_IN_SPANISH = {"ISO", "Flash", "Focal", "Photo Stats", "version",
                   "month.jun", "month.may", "{rate:.0f}/s"}


def test_every_spanish_string_differs_from_english():
    """A catalogue entry that was copied over is a missing translation."""
    english = i18n.load("en")
    spanish = i18n.load("es")
    identical = [key for key, value in spanish.items()
                 if key in english and value == english[key]
                 and key not in SAME_IN_SPANISH]
    assert identical == []


def test_no_placeholder_was_lost_in_translation():
    """Every {name} in the English string must survive into the translation."""
    import re

    placeholder = re.compile(r"\{(\w+)\}")
    english = i18n.load("en")
    problems = []
    for key, source in english.items():
        target = i18n.load("es").get(key)
        if target is None:
            continue
        if set(placeholder.findall(source)) != set(placeholder.findall(target)):
            problems.append(key)
    assert problems == []


def test_translations_are_complete():
    assert i18n.missing_keys("es") == []


def test_audit_reports_nothing_missing(capsys):
    assert i18n.audit() == 0
    assert "untranslated" in capsys.readouterr().out


def test_unknown_key_returns_the_key_itself():
    i18n.set_language("es")
    assert i18n.tr("a string nobody wrote down") == "a string nobody wrote down"


def test_a_missing_translation_is_reported_not_hidden():
    """An absent key is marked, so a test or audit can notice it."""
    i18n.set_language("es")
    catalogue = dict(i18n.load("es"))
    catalogue.pop("Scan")
    i18n.load.cache_clear()
    original = i18n.load

    def patched(language):
        return catalogue if language == "es" else original(language)

    i18n.load = patched
    try:
        assert "Scan" in i18n.missing_keys("es")
        assert isinstance(i18n.tr("Scan"), i18n._Missing)
    finally:
        i18n.load = original
        i18n.load.cache_clear()


def test_placeholders_are_filled():
    i18n.set_language("es")
    assert i18n.tr("{count} photos", count="12") == "12 fotos"


def test_a_broken_translation_cannot_take_the_window_down():
    """A malformed catalogue entry falls back to the raw template."""
    i18n.set_language("es")
    catalogue = dict(i18n.load("es"))
    catalogue["{count} fotos"] = "{missing}"
    i18n.load.cache_clear()
    original = i18n.load
    i18n.load = lambda language: catalogue if language == "es" else original(language)
    try:
        assert i18n.tr("{count} fotos", count="1") == "{missing}"
    finally:
        i18n.load = original
        i18n.load.cache_clear()


def test_catalogues_are_valid_json_on_disk():
    for code in i18n.languages():
        data = json.loads(i18n.catalogue_path(code).read_text(encoding="utf-8"))
        assert data and all(isinstance(k, str) and isinstance(v, str)
                            for k, v in data.items())


def test_month_names_follow_the_language():
    from photostats.core.queries import month_label

    i18n.set_language("en")
    english = month_label(3)
    i18n.set_language("es")
    assert month_label(3) == "mar"
    assert month_label(3) != english
    assert month_label(13) == "?"
    assert month_label(None) == "?"


def test_insights_are_stored_as_keys_not_english():
    """The engine has to be language-agnostic or exports would be stuck."""
    from photostats.core.insights import Insight

    insight = Insight("insight.no_flash")
    i18n.set_language("en")
    english = insight.text
    i18n.set_language("es")
    assert insight.text != english
