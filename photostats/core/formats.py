"""Supported file formats and the preference order used to group RAW+JPEG pairs.

When a folder holds several files with the same base name (for example
``IMG_4821.CR3`` and ``IMG_4821.JPG``) we keep exactly one, chosen by the
priority below, so a single shot is counted once.
"""

from __future__ import annotations

RAW_EXTENSIONS = frozenset({
    "3fr", "arw", "cr2", "cr3", "crw", "dng", "eip", "erf", "iiq", "kdc", "mdc",
    "mos", "mraw", "mrw", "nef", "nrw", "orf", "pef", "raf", "raw", "rw2", "rwl",
    "rwz", "sr2", "srf", "srw", "x3f",
})
TIFF_EXTENSIONS = frozenset({"tif", "tiff"})
HEIC_EXTENSIONS = frozenset({"heic", "heif"})
PNG_EXTENSIONS = frozenset({"png"})
JPEG_EXTENSIONS = frozenset({"jpg", "jpeg"})

ALLOWED_EXTENSIONS = (
    RAW_EXTENSIONS | TIFF_EXTENSIONS | HEIC_EXTENSIONS | PNG_EXTENSIONS | JPEG_EXTENSIONS
)

#: Higher wins when the same base name appears with several extensions.
PRIORITY = {}
PRIORITY.update(dict.fromkeys(RAW_EXTENSIONS, 3))
PRIORITY.update(dict.fromkeys(TIFF_EXTENSIONS, 2))
PRIORITY.update(dict.fromkeys(HEIC_EXTENSIONS, 2))
PRIORITY.update(dict.fromkeys(PNG_EXTENSIONS, 1))
PRIORITY.update(dict.fromkeys(JPEG_EXTENSIONS, 1))


def extension_of(name: str) -> str:
    """Lower-case extension without the dot, or '' when there is none."""
    dot = name.rfind(".")
    if dot <= 0 or dot == len(name) - 1:
        return ""
    return name[dot + 1 :].lower()


def is_allowed(name: str) -> bool:
    return extension_of(name) in ALLOWED_EXTENSIONS


def priority_of(ext: str) -> int:
    return PRIORITY.get(ext.lower(), 0)


def is_raw(ext: str) -> bool:
    return ext.lower() in RAW_EXTENSIONS


def file_type_of(ext: str) -> str:
    """Coarse bucket stored in the database and offered as a filter."""
    ext = ext.lower()
    if ext in RAW_EXTENSIONS:
        return "raw"
    if ext in JPEG_EXTENSIONS or ext in PNG_EXTENSIONS:
        return "jpeg"
    if ext in TIFF_EXTENSIONS or ext in HEIC_EXTENSIONS:
        return "tiff"
    return "other"
