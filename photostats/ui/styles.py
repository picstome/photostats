"""Widget-level stylesheets that depend on the active theme."""

from __future__ import annotations

from .theme import mono_stack


def stylesheet(theme) -> str:
    """Styling for the shared widgets; the global QSS lives in theme.py."""
    return f"""
    QPushButton {{
        background: {theme.card};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 8px;
        padding: 7px 14px;
    }}
    QPushButton:hover {{ background: {theme.card_hover}; }}
    QPushButton:pressed {{ background: {theme.bg_alt}; }}
    QPushButton:disabled {{ color: {theme.text_faint}; border-color: {theme.border}; }}

    QPushButton#primary {{
        background: {theme.accent};
        color: {theme.accent_text};
        border: none;
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {theme.accent}; }}
    QPushButton#primary:disabled {{
        background: {theme.bar_bg};
        color: {theme.text_faint};
    }}
    QPushButton#danger {{
        background: transparent;
        color: {theme.accent};
        border: 1px solid {theme.accent};
        font-weight: 600;
    }}
    QPushButton#secondary {{
        background: {theme.card};
        border: 1px solid {theme.border};
    }}
    QPushButton#chipButton {{
        padding: 4px 10px;
        font-size: 12px;
        border-radius: 12px;
        background: {theme.bg_alt};
    }}
    QPushButton#chipButton:hover {{ background: {theme.card_hover}; }}
    QPushButton#linkButton {{
        background: transparent;
        border: none;
        color: {theme.accent};
        padding: 2px 6px;
        font-size: 12px;
    }}

    QLineEdit, QDateEdit, QComboBox, QSpinBox {{
        background: {theme.bg_alt};
        border: 1px solid {theme.border};
        border-radius: 8px;
        padding: 6px 10px;
        selection-background-color: {theme.accent};
        selection-color: {theme.accent_text};
    }}
    QLineEdit:focus, QDateEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border-color: {theme.accent};
    }}
    /* One rule for every card heading, so they cannot drift apart. */
    QLabel#cardTitle {{
        font-size: 13px;
        font-weight: 700;
        color: {theme.text};
    }}
    /* Sidebar section headings: they are clickable, so say so on hover. */
    QToolButton#sectionHeader {{
        border: none;
        font-weight: 600;
        font-size: 13px;
        padding: 3px 0;
        border-radius: 5px;
        color: {theme.text};
        text-align: left;
    }}
    QToolButton#sectionHeader:hover {{
        background: {theme.card_hover};
    }}
    QToolButton#sectionHeader::indicator {{
        width: 12px;
    }}

    /* The header's identity: an eyebrow saying what this is, the library as the
       title, and the path underneath to check it against. */
    QLabel#libraryEyebrow {{
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: {theme.text_faint};
    }}
    QLabel#libraryName {{
        font-size: 19px;
        font-weight: 700;
        color: {theme.text};
    }}
    QLabel#libraryPath {{
        font-family: {mono_stack()};
        font-size: 11px;
        color: {theme.text_faint};
    }}

    /* Icon-only buttons: square, no text, no border to fight the glyph. */
    QToolButton#iconButton {{
        background: transparent;
        border: none;
        border-radius: 8px;
        padding: 5px;
        color: {theme.text_dim};
    }}
    QToolButton#iconButton:hover {{
        background: {theme.card_hover};
        color: {theme.text};
    }}

    /* The status bar: one size for the message, one for the detail beside it. */
    QLabel#statusText {{
        font-size: 12px;
        color: {theme.text};
    }}
    QLabel#statusMeta {{
        font-family: {mono_stack()};
        font-size: 11px;
        color: {theme.text_faint};
    }}

    /* The drop-down arrows are left to the style. Drawing a triangle with
       transparent borders (the usual CSS trick) does not work on these
       subcontrols: Qt paints the border box as a small grey square instead, so
       the native arrow — which follows the palette — is the better answer. */
    QComboBox QAbstractItemView {{
        background: {theme.card};
        border: 1px solid {theme.border};
        selection-background-color: {theme.card_hover};
        outline: none;
    }}

    /* The calendar popup. The global rule makes every QAbstractScrollArea
       transparent, which left the day grid with no background at all (black in
       the popup), and Qt paints weekends red by default. Both are overridden
       here, and the weekday text formats are set from the theme in
       ``filter_panel._CalendarDateEdit``. */
    QCalendarWidget {{
        background: {theme.card};
        border: 1px solid {theme.border};
        border-radius: 8px;
    }}
    QCalendarWidget QWidget#qt_calendar_navigationbar {{
        background: {theme.bg_alt};
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
    }}
    QCalendarWidget QToolButton {{
        color: {theme.text};
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 4px 10px;
        font-weight: 600;
    }}
    QCalendarWidget QToolButton:hover {{ background: {theme.card_hover}; }}
    QCalendarWidget QToolButton:pressed {{ background: {theme.bar_bg}; }}
    QCalendarWidget QToolButton::menu-indicator {{ image: none; }}
    QCalendarWidget QMenu {{
        background: {theme.card};
        color: {theme.text};
        border: 1px solid {theme.border};
    }}
    QCalendarWidget QSpinBox {{
        background: {theme.bg_alt};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 6px;
        selection-background-color: {theme.accent};
    }}
    QCalendarWidget QAbstractItemView {{
        background: {theme.card};
        color: {theme.text};
        selection-background-color: {theme.accent};
        selection-color: {theme.accent_text};
        outline: none;
    }}
    QCalendarWidget QAbstractItemView:disabled {{ color: {theme.text_faint}; }}
    QCalendarWidget QHeaderView::section {{
        background: {theme.card};
        color: {theme.text_dim};
        border: none;
        padding: 4px 0;
    }}
    QCalendarWidget QWidget#qt_tableview_cornerbutton {{
        background: {theme.card};
        border: none;
    }}
    /* Spin-box arrows are drawn by the platform style. Reserving a width for
       them without also giving them an origin made Qt stack them; the headless
       test platform does not paint them at all, so this is left to Qt. */
    QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; }}

    QCheckBox, QRadioButton {{ spacing: 8px; padding: 2px 0; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 15px; height: 15px;
        border: 1px solid {theme.border};
        background: {theme.bg_alt};
    }}
    QCheckBox::indicator {{ border-radius: 4px; }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background: {theme.accent};
        border-color: {theme.accent};
    }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {theme.accent}; }}

    QToolTip {{
        background: {theme.card};
        color: {theme.text};
        border: 1px solid {theme.border};
        padding: 6px 8px;
    }}

    QLabel#hint {{ color: {theme.text_faint}; font-size: 11px; }}
    QLabel#tileCaption {{ color: {theme.text_faint}; font-size: 11px; }}
    """
