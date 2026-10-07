"""Themes for Photo Stats, in the Picstome house colours.

The palette is fixed by the brand; the two themes are different ways of spending
it rather than two different brands.

    Pine Blue      #316D61   primary: charts, selection, focus
    Graphite       #322F30   dark surfaces, and text on light
    Vibrant Coral  #EE6958   the one thing you press: Scan, Stop
    Tea Green      #C6D8AF   soft fills: chips, the insights row
    Floral White   #FFF9EC   light surfaces, and text on dark

Derived tones are computed from those five rather than invented, so adding a
shade cannot drift away from the brand.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette

# -- the brand -------------------------------------------------------------
PINE_BLUE = "#316D61"
GRAPHITE = "#322F30"
VIBRANT_CORAL = "#EE6958"
TEA_GREEN = "#C6D8AF"
FLORAL_WHITE = "#FFF9EC"

#: Typeface, with a fallback stack so the app is still correct on a machine
#: where the font is not installed.
BRAND_FONT = "League Spartan"
_FALLBACKS = ("Avenir Next", "Segoe UI", "Helvetica Neue", "Arial")
#: Monospace equivalents. "monospace" itself is an X11 generic that macOS and
#: Windows do not have, and asking for it costs a font lookup every launch.
_MONO_FALLBACKS = ("Menlo", "SF Mono", "Consolas", "Monaco", "DejaVu Sans Mono",
                   "Courier New")


def font_stack(installed: Iterable[str] | None = None) -> str:
    """The brand font first, but only if it is actually available.

    Naming a font Qt cannot find is not free: Qt resolves font aliases at
    startup and prints "Populating font family aliases took 100ms" to the
    console on every launch. Since the font ships as an optional asset, the
    stylesheet has to be built at runtime rather than written out in advance.

    *installed* exists so this can be tested without a display.
    """
    if installed is None:
        from PySide6.QtGui import QFontDatabase

        installed = QFontDatabase.families()
    families = set(installed)
    available = [name for name in (BRAND_FONT, *_FALLBACKS) if name in families]
    if not available:
        available = [_FALLBACKS[-1]]
    # No trailing generic: "sans-serif" is itself resolved through the same
    # alias machinery, and Arial is always installed as the last resort anyway.
    return ", ".join(f'"{name}"' for name in available)


def _mix(hex_a: str, hex_b: str, amount: float) -> str:
    """Blend two colours; *amount* 0 gives *hex_a*, 1 gives *hex_b*."""
    a, b = QColor(hex_a), QColor(hex_b)
    return QColor(
        round(a.red() + (b.red() - a.red()) * amount),
        round(a.green() + (b.green() - a.green()) * amount),
        round(a.blue() + (b.blue() - a.blue()) * amount),
    ).name()


def _lift(hex_colour: str, percent: int) -> str:
    return QColor(hex_colour).lighter(percent).name()


# Roles that are not part of the five brand colours but are still brand-adjacent
# rather than arbitrary: the destructive action is the coral, the confirm action
# is the pine.
DANGER = VIBRANT_CORAL
SUCCESS = _lift(TEA_GREEN, 105)
WARNING = _lift(VIBRANT_CORAL, 112)

SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24}


@dataclass(frozen=True)
class Theme:
    name: str
    is_dark: bool
    bg: str
    bg_alt: str
    card: str
    card_hover: str
    border: str
    text: str
    text_dim: str
    text_faint: str
    bar_bg: str
    accent: str
    #: Softer accent for unselected bars and table row highlights.
    accent_dim: str
    accent_text: str

    def color(self, role: str) -> QColor:
        return QColor(getattr(self, role))


DARK = Theme(
    name="dark",
    is_dark=True,
    # Graphite, lifted just off pure black so the pine still reads as colour.
    bg=_mix(GRAPHITE, "#000000", 0.62),
    bg_alt=_mix(GRAPHITE, "#000000", 0.55),
    card=_mix(GRAPHITE, "#000000", 0.44),
    card_hover=_mix(GRAPHITE, "#000000", 0.34),
    border=_mix(GRAPHITE, FLORAL_WHITE, 0.20),
    text=FLORAL_WHITE,
    text_dim=_mix(FLORAL_WHITE, GRAPHITE, 0.38),
    text_faint=_mix(FLORAL_WHITE, GRAPHITE, 0.58),
    bar_bg=_mix(GRAPHITE, FLORAL_WHITE, 0.13),
    # Pine is too dark to read as an accent on a dark surface, so the pine hue
    # is carried at a lighter tint rather than replaced.
    accent=_lift(PINE_BLUE, 135),
    accent_dim=_lift(PINE_BLUE, 112),
    accent_text=GRAPHITE,
)

LIGHT = Theme(
    name="light",
    is_dark=False,
    bg=FLORAL_WHITE,
    bg_alt=_mix(FLORAL_WHITE, TEA_GREEN, 0.16),
    card="#ffffff",
    card_hover=_mix(FLORAL_WHITE, TEA_GREEN, 0.30),
    border=_mix(FLORAL_WHITE, GRAPHITE, 0.16),
    text=GRAPHITE,
    text_dim=_mix(GRAPHITE, FLORAL_WHITE, 0.28),
    text_faint=_mix(GRAPHITE, FLORAL_WHITE, 0.50),
    #: Recessive, but still visibly a track to fill rather than a hairline.
    bar_bg=_mix(FLORAL_WHITE, GRAPHITE, 0.14),
    accent=PINE_BLUE,
    #: Mixed to 3.1:1 against the white card, the WCAG minimum for a graphic
    #: that carries meaning. At the paler 2.1:1 the bars read as decoration
    #: rather than as data, which is the one thing a chart cannot afford.
    accent_dim=_mix(PINE_BLUE, FLORAL_WHITE, 0.30),
    accent_text=FLORAL_WHITE,
)

THEMES = {"dark": DARK, "light": LIGHT}


def mono_stack(installed: Iterable[str] | None = None) -> str:
    """A fixed-width stack naming only fonts that are present.

    Used for the folder path, where the shape of the characters matters.
    """
    if installed is None:
        from PySide6.QtGui import QFontDatabase

        installed = QFontDatabase.families()
    families = set(installed)
    chosen = [name for name in _MONO_FALLBACKS if name in families]
    return '"%s"' % (chosen[0] if chosen else "Courier New")


def apply_base_font(app) -> str:
    """Point the application font at a family that actually exists.

    Qt's own default on macOS is the literal string "Sans Serif", which is an
    X11 convention and is not installed — so Qt has to resolve a family it
    cannot find, and prints "Populating font family aliases took 100ms" to the
    console on every launch. Naming a real family removes the lookup and makes
    the base size deterministic too.
    """
    from PySide6.QtGui import QFont

    family = font_stack().split(",")[0].strip('"')
    font = QFont(family)
    font.setPointSize(10)
    app.setFont(font)
    return family


def palette(theme: Theme) -> QPalette:
    """Build a QPalette so that native dialogs and controls match the theme."""
    p = QPalette()
    p.setColor(QPalette.Window, QColor(theme.bg))
    p.setColor(QPalette.WindowText, QColor(theme.text))
    p.setColor(QPalette.Base, QColor(theme.bg_alt))
    p.setColor(QPalette.AlternateBase, QColor(theme.card))
    p.setColor(QPalette.Text, QColor(theme.text))
    p.setColor(QPalette.Button, QColor(theme.card))
    p.setColor(QPalette.ButtonText, QColor(theme.text))
    p.setColor(QPalette.Highlight, QColor(theme.accent))
    p.setColor(QPalette.HighlightedText, QColor(theme.accent_text))
    p.setColor(QPalette.ToolTipBase, QColor(theme.card))
    p.setColor(QPalette.ToolTipText, QColor(theme.text))
    p.setColor(QPalette.PlaceholderText, QColor(theme.text_faint))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(theme.text_faint))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(theme.text_faint))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(theme.text_faint))
    return p


def stylesheet(theme: Theme) -> str:
    """Global QSS. Widget-specific styling lives with the widget."""
    border = theme.border
    return f"""
    QWidget {{
        background: {theme.bg};
        color: {theme.text};
        font-family: {font_stack()};
        font-size: 13px;
    }}
    QToolTip {{
        background: {theme.card};
        color: {theme.text};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 6px 8px;
    }}
    QScrollArea, QAbstractScrollArea {{
        border: none;
        background: transparent;
    }}
    /* A label must never paint its own background: inside a card it would
       cover the surface with the window colour and read as a stray bar. */
    QLabel {{
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {theme.bar_bg}; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {theme.text_faint}; }}
    QScrollBar:horizontal {{
        background: transparent; height: 10px; margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {theme.bar_bg}; border-radius: 5px; min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {theme.text_faint}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QMenu {{
        background: {theme.card}; border: 1px solid {border}; border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {theme.card_hover}; }}
    QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}
    QLabel#selectionBadge {{
        background: {theme.accent}; color: {theme.accent_text};
        border-radius: 9px; font-size: 11px; font-weight: 600;
    }}
    QLabel#selectionBadge:hover {{ background: {theme.accent_dim}; }}
    """


def combined(theme) -> str:
    """Global QSS plus the per-widget styles."""
    from . import styles

    return stylesheet(theme) + styles.stylesheet(theme)
