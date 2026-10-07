"""A minimal but genuine DNG file, for testing RAW handling.

Copying a JPEG and renaming it to ``.NEF`` does not work: exiftool inspects the
content, refuses the write, and there is no RAW anywhere in the test library —
which means duplicate grouping has never actually been exercised against a real
RAW. A DNG is a TIFF with a few extra tags, and a TIFF is little enough to write
by hand, so this produces one small enough to commit and real enough for exiftool
to read as a camera original.

Only the tags the indexer cares about are present.
"""

from __future__ import annotations

import struct
from pathlib import Path

# TIFF field types.
SHORT, LONG, RATIONAL, ASCII, BYTE = 3, 4, 5, 2, 1
_TYPE_SIZE = {BYTE: 1, ASCII: 1, SHORT: 2, LONG: 4, RATIONAL: 8}

#: A 2x2 RGB image, enough for exiftool to report a FileType and a size.
_PIXELS = b"\xff\x00\x00\xff\x00\x00\x00\x00\x00\x00\xff\x00"


def _rational(value: float) -> bytes:
    """EXIF stores fractions as unsigned numerator/denominator."""
    if value >= 1:
        return struct.pack("<II", int(round(value * 1000)), 1000)
    return struct.pack("<II", 1, int(round(1 / value)))


class _Ifd:
    """One image file directory, laid out in memory."""

    def __init__(self) -> None:
        self.entries: list[tuple[int, int, int, bytes]] = []
        self._placed: dict[int, int] = {}

    def add(self, tag: int, kind: int, count: int, payload: bytes) -> None:
        self.entries.append((tag, kind, count, payload))

    def short(self, tag: int, value: int) -> None:
        self.add(tag, SHORT, 1, struct.pack("<H", value))

    def long(self, tag: int, value: int) -> None:
        self.add(tag, LONG, 1, struct.pack("<I", value))

    def ascii(self, tag: int, value: str) -> None:
        self.add(tag, ASCII, len(value) + 1, value.encode("ascii") + b"\x00")

    def rational(self, tag: int, value: float) -> None:
        self.add(tag, RATIONAL, 1, _rational(value))

    def blob(self, tag: int, payload: bytes) -> None:
        self.add(tag, BYTE, len(payload), payload)

    def size(self) -> int:
        return 2 + 12 * len(self.entries) + 4

    def oversized(self) -> list[bytes]:
        """The payloads too large for their entry, in order."""
        return [payload for _tag, kind, count, payload in self.entries
                if _TYPE_SIZE[kind] * count > 4]

    def overflow(self, at: int, heap: dict[int, bytes]) -> int:
        """Place this directory's oversized values from *at*; return the next free.

        Overflow has to come after *both* directories, not immediately after
        this one, or the next directory lands on top of it.
        """
        for tag, kind, count, payload in self.entries:
            if _TYPE_SIZE[kind] * count > 4:
                heap[at] = payload
                self._placed[tag] = at
                at += len(payload) + (len(payload) % 2)
        return at

    def write(self, out: bytearray, heap: dict[int, bytes]) -> None:
        """Append this directory to *out*, resolving any oversized values."""
        out.extend(struct.pack("<H", len(self.entries)))   # entry count
        for tag, kind, count, payload in self.entries:
            if _TYPE_SIZE[kind] * count <= 4:
                value = payload + b"\x00" * (4 - len(payload))
            else:
                value = struct.pack("<I", self._where(tag))
            out.extend(struct.pack("<HHI", tag, kind, count) + value)
        out.extend(struct.pack("<I", 0))          # no next IFD

    def _where(self, tag: int) -> int:
        return self._placed[tag]


def write_dng(
    path: Path,
    *,
    make: str = "NIKON CORPORATION",
    model: str = "NIKON Z 8",
    lens: str = "NIKKOR Z 24-70mm f/2.8 S",
    iso: int = 400,
    shutter: float = 1 / 250,
    fnumber: float = 2.8,
    focal: float = 35,
    taken: str = "2024:05:01 10:00:00",
) -> Path:
    """Write a small DNG at *path* and return it."""
    exif = _Ifd()
    exif.rational(33434, shutter)                 # ExposureTime
    exif.rational(33437, fnumber)                 # FNumber
    exif.short(34855, iso)                        # ISOSpeedRatings
    exif.ascii(36867, taken)                      # DateTimeOriginal
    exif.rational(37386, focal)                   # FocalLength
    exif.ascii(42036, lens)                       # LensModel

    ifd0 = _Ifd()
    ifd0.long(254, 0)                             # NewSubfileType: main image
    ifd0.ascii(271, make)
    ifd0.ascii(272, model)
    ifd0.short(277, 3)                            # SamplesPerPixel
    ifd0.long(278, 2)                             # RowsPerStrip
    ifd0.long(284, 1)                             # PlanarConfiguration
    ifd0.ascii(305, "photostats test fixture")
    ifd0.blob(50706, bytes((1, 4, 0, 0)))         # DNGVersion
    ifd0.long(34665, 0)                           # ExifIFD pointer, patched below
    ifd0.long(273, 0)                             # StripOffsets, patched below

    header = 8
    ifd0_at = header
    exif_at = ifd0_at + ifd0.size()
    data_at = exif_at + exif.size()
    # Patch the two offsets that had to be known in advance, then order the
    # entries as TIFF requires (ascending tag).
    for index, (tag, _kind, _count, _payload) in enumerate(ifd0.entries):
        if tag == 34665:
            ifd0.entries[index] = (tag, LONG, 1, struct.pack("<I", exif_at))
        elif tag == 273:
            ifd0.entries[index] = (tag, LONG, 1, struct.pack("<I", data_at))
    ifd0.entries.sort(key=lambda item: item[0])
    exif.entries.sort(key=lambda item: item[0])

    # Where do the oversized values go? Only knowable once both directories are
    # placed, so this is computed before anything is written.
    heap: dict[int, bytes] = {}
    ifd0.overflow(exif_at + exif.size(), heap)
    exif.overflow(exif_at + exif.size() + sum(
        len(v) + (len(v) % 2) for v in ifd0.oversized()), heap)

    out = bytearray(b"II" + struct.pack("<HI", 42, ifd0_at))
    ifd0.write(out, heap)
    exif.write(out, heap)
    for offset in sorted(heap):
        out.extend(heap[offset])
    out.extend(_PIXELS)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path
