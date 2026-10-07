"""The monthly GitHub Releases check: parsing, throttling and asset choice.

Nothing here touches the network — ``urlopen`` is replaced — so the tests are
fast and work offline, which is the whole point of keeping this module free of
Qt and of any HTTP library.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta

import pytest

from photostats.core import updates


def test_parse_version_reads_tags():
    assert updates.parse_version("1.2.3") == (1, 2, 3)
    assert updates.parse_version("v1.2.3") == (1, 2, 3)
    assert updates.parse_version("v1.2.0-beta.1") == (1, 2, 0)
    assert updates.parse_version("1.2") == (1, 2)


def test_is_newer_compares_numerically_not_as_text():
    assert updates.is_newer("1.10.0", "1.9.0")      # string order would say no
    assert updates.is_newer("v2.0.0", "1.99.99")
    assert not updates.is_newer("1.0.0", "1.0.0")
    assert not updates.is_newer("0.9.0", "1.0.0")


def test_due_only_after_the_interval():
    now = datetime(2026, 10, 7, 12, 0, 0)
    assert updates.due(None, now)                          # never checked
    assert not updates.due(now - timedelta(days=29), now)
    assert updates.due(now - timedelta(days=30), now)
    assert updates.due(now - timedelta(days=400), now)


@pytest.mark.parametrize("system,machine,expected", [
    ("Darwin", "arm64", "Photo Stats-arm64.dmg"),
    ("Darwin", "aarch64", "Photo Stats-arm64.dmg"),
    ("Darwin", "x86_64", "Photo Stats-x64.dmg"),
    ("Windows", "AMD64", "PhotoStats-Setup.exe"),
    ("Linux", "x86_64", "PhotoStats-linux.tar.gz"),
])
def test_asset_name_matches_what_the_workflow_uploads(system, machine, expected):
    assert updates.asset_name(system, machine) == expected


class _Response(io.BytesIO):
    """Enough of an HTTP response for ``json.load`` and ``with``."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _payload(tag="v1.1.0"):
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/picstome/photostats/releases/tag/{tag}",
        "assets": [
            {"name": "Photo Stats-arm64.dmg", "browser_download_url": "https://x/a.dmg"},
            {"name": "PhotoStats-Setup.exe", "browser_download_url": "https://x/setup.exe"},
        ],
    }


def _serve(monkeypatch, body):
    payload = json.dumps(body).encode()
    monkeypatch.setattr(updates.urllib.request, "urlopen",
                        lambda *a, **k: _Response(payload))


def test_fetch_latest_parses_a_release(monkeypatch):
    _serve(monkeypatch, _payload())
    release = updates.fetch_latest()

    assert release is not None
    assert release.version == "1.1.0"
    assert release.url.endswith("/v1.1.0")
    assert release.asset_for("Darwin", "arm64") == "https://x/a.dmg"
    assert release.asset_for("Windows", "AMD64") == "https://x/setup.exe"
    assert release.asset_for("Linux", "x86_64") == ""   # not in this release


def test_fetch_latest_is_none_when_offline(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("no network")

    monkeypatch.setattr(updates.urllib.request, "urlopen", boom)
    assert updates.fetch_latest() is None


def test_fetch_latest_is_none_for_unexpected_json(monkeypatch):
    _serve(monkeypatch, ["not", "a", "release"])
    assert updates.fetch_latest() is None


def test_available_update_only_when_strictly_newer(monkeypatch):
    _serve(monkeypatch, _payload(tag="v1.1.0"))

    assert updates.available_update(current="1.0.0") is not None
    assert updates.available_update(current="1.1.0") is None
    assert updates.available_update(current="2.0.0") is None
