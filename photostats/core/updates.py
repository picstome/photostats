"""Ask GitHub Releases whether a newer Photo Stats exists.

GitHub Releases is where the builds are published, so the whole check is one
GET to its public API and a version comparison. It runs at most once a month,
sends no token, and does nothing with the answer except offer a download link —
a failed check is silent, because being offline is not worth a dialog.

Deliberately Qt-free so it can be tested without a display.
"""

from __future__ import annotations

import json
import platform
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .. import REPO_SLUG, __version__

RELEASES_API = "https://api.github.com/repos/{repo}/releases/latest"
TIMEOUT_SECONDS = 6

#: How long between automatic checks. A desktop app does not need to hear about
#: a release within the hour; once a month keeps the call count negligible
#: against GitHub's 60-requests-an-hour unauthenticated limit.
CHECK_INTERVAL_DAYS = 30


@dataclass(frozen=True)
class Release:
    """A published release, as much of it as the app cares about."""

    version: str          # "1.1.0" — the tag without its leading "v"
    tag: str              # "v1.1.0"
    url: str              # the release page
    assets: dict[str, str] = field(default_factory=dict)  # name -> download url

    def asset_for(self, system: str | None = None, machine: str | None = None) -> str:
        """The download for this platform, or "" when the release has none."""
        return self.assets.get(asset_name(system, machine), "")


def parse_version(text: str) -> tuple[int, ...]:
    """``"v1.2.3"`` -> ``(1, 2, 3)``; a pre-release suffix is ignored.

    Only the numeric head is compared, which is all the tags here use. A part
    that is not a number ends the version rather than being guessed at.
    """
    core = text.strip().lstrip("vV").split("-")[0].split("+")[0]
    parts: list[int] = []
    for chunk in core.split("."):
        if not chunk.isdigit():
            break
        parts.append(int(chunk))
    return tuple(parts)


def is_newer(remote: str, current: str = __version__) -> bool:
    """True when *remote* is a later version than *current*."""
    return parse_version(remote) > parse_version(current)


def due(last_checked: datetime | None, now: datetime | None = None,
        interval_days: int = CHECK_INTERVAL_DAYS) -> bool:
    """Whether enough time has passed since the last check to run another."""
    if last_checked is None:
        return True
    return (now or datetime.now()) - last_checked >= timedelta(days=interval_days)


def asset_name(system: str | None = None, machine: str | None = None) -> str:
    """The release asset that belongs on this machine.

    The names match what ``.github/workflows/build.yml`` uploads; the release
    page is the fallback when the expected asset is not there.
    """
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    if system == "Darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
        return f"Photo Stats-{arch}.dmg"
    if system == "Windows":
        return "PhotoStats-Setup.exe"
    return "PhotoStats-linux.tar.gz"


def fetch_latest(repo: str = REPO_SLUG, timeout: float = TIMEOUT_SECONDS) -> Release | None:
    """The latest release, or None when it cannot be fetched.

    Every failure — no network, a timeout, a rate limit, unexpected JSON — is
    None. The caller treats that as "nothing to report", never as an error.
    """
    request = urllib.request.Request(
        RELEASES_API.format(repo=repo),
        headers={
            "User-Agent": f"PhotoStats/{__version__}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    tag = str(payload.get("tag_name") or "")
    if not tag:
        return None
    assets = {
        str(asset["name"]): str(asset.get("browser_download_url") or "")
        for asset in payload.get("assets") or []
        if isinstance(asset, dict) and asset.get("name")
    }
    return Release(
        version=tag.lstrip("vV"),
        tag=tag,
        url=str(payload.get("html_url") or ""),
        assets=assets,
    )


def available_update(current: str = __version__, **kwargs) -> Release | None:
    """The newer release, if the latest one is newer than *current*."""
    release = fetch_latest(**kwargs)
    if release is not None and is_newer(release.version, current):
        return release
    return None
