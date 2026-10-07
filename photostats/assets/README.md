# Brand assets

Drop the Picstome files here. Nothing in this folder is required to run the app:
a missing font falls back to the system stack and a missing logo falls back to a
mark drawn in the brand's pine blue. Both are picked up automatically at startup
— there is no build step and no code to change.

## `fonts/`

League Spartan. It is licensed under the SIL Open Font License, so it can be
shipped with the app.

```
fonts/LeagueSpartan-VariableFont_wght.ttf
```

Any `.ttf`, `.otf` or `.ttc` in this folder is registered with Qt at startup
(`photostats.ui.assets.install_fonts`). Put the variable font in if you have it,
since that is what covers the full weight range in one file.

## `logos/`

```
logos/picstome-mark.png       the "p" aperture mark: window icon, about box
logos/picstome-wordmark.png   the full "picstome" lockup
```

The mark is used as the application icon. The wordmark is not drawn anywhere yet
— the title bar says "Photo Stats" — so it is only picked up if you want to
show it somewhere.

Anything with those names works; PNG with transparency, 512×512 for the mark.

## Where the colours live

The five brand colours are constants in `photostats/ui/theme.py` (`PINE_BLUE`,
`GRAPHITE`, `VIBRANT_CORAL`, `TEA_GREEN`, `FLORAL_WHITE`). Every other tone in
both themes is mixed from those five rather than written by hand, so a new shade
cannot drift away from the brand.