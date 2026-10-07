"""Where the app's own files live: fonts and logos.

Both are optional. A missing font simply means the interface falls back to the
system stack, and a missing logo means the window uses the default icon, so the
app has to run correctly with the assets folder absent — which is also what
makes it safe to install from a source checkout.
"""

from __future__ import annotations

from pathlib import Path

#: ``photostats/assets``. Packaged data is collected from here.
ASSETS = Path(__file__).resolve().parent.parent / "assets"
FONTS = ASSETS / "fonts"
LOGOS = ASSETS / "logos"

#: Preferred font file names, best first. League Spartan is a variable font in
#: two common flavours, either of which works.
FONT_FILES = (
    "LeagueSpartan-VariableFont_wght.ttf",
    "LeagueSpartan-Regular.ttf",
    "LeagueSpartan[wght].ttf",
)

#: The mark on its own, for the window icon and the about box.
LOGO_MARK = "picstome-mark.png"
LOGO_WORDMARK = "picstome-wordmark.png"


def font_files() -> list[Path]:
    """Every League Spartan file that is actually present."""
    if not FONTS.is_dir():
        return []
    return sorted(
        path for path in FONTS.iterdir()
        if path.suffix.lower() in (".ttf", ".otf", ".ttc")
    )


def logo(name: str) -> Path | None:
    """The path to a logo file, or None when it has not been supplied."""
    candidate = LOGOS / name
    return candidate if candidate.is_file() else None


def install_fonts() -> list[Path]:
    """Register the bundled fonts with Qt. Returns what was loaded.

    Called once at startup, before any widget exists, because a widget's font
    is fixed when it is built.
    """
    from PySide6.QtGui import QFontDatabase

    loaded = []
    for path in font_files():
        if QFontDatabase.addApplicationFont(str(path)) != -1:
            loaded.append(path)
    return loaded
