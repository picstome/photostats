"""Command line interface.

``photostats --stats ~/Pictures`` prints the report without opening a window,
which keeps the original workflow (and the blog post's instructions) working.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import APP_NAME, __version__
from .core import export
from .core.exiftool import find_exiftool, install_hint
from .core.filters import (
    Filter,
)
from .core.indexer import Indexer
from .core.legacy import import_legacy_cache, legacy_candidates
from .core.queries import PhotoStore
from .core.scanner import ROOT_DIR  # noqa: F401  (kept for symmetry with the engine)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="photostats-cli", description=f"{APP_NAME} — photo metadata analyzer"
    )
    parser.add_argument("folder", nargs="?", default=".", help="photo library (default: .)")
    parser.add_argument("--gui", action="store_true", help="open the desktop app instead")
    parser.add_argument("--stats", action="store_true", help="print the report and exit")
    parser.add_argument("--csv", metavar="FILE", help="export the filtered photos to CSV")
    parser.add_argument("--json", metavar="FILE", help="export a full JSON report")
    parser.add_argument("--no-scan", action="store_true",
                        help="use the cache only, do not look for new photos")
    parser.add_argument("--reindex", action="store_true",
                        help="clear the cache and read every photo again")
    parser.add_argument("--import-legacy", action="store_true",
                        help="import a cache from the original script, then exit")
    parser.add_argument("--camera", action="append", default=[], help="filter by camera model")
    parser.add_argument("--lens", action="append", default=[], help="filter by lens model")
    parser.add_argument("--iso-min", type=int)
    parser.add_argument("--iso-max", type=int)
    parser.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return parser


def filters_from_args(args) -> Filter:
    from dataclasses import replace

    filters = Filter(
        cameras=frozenset(args.camera),
        lenses=frozenset(args.lens),
        iso_min=args.iso_min,
        iso_max=args.iso_max,
    )
    if args.date_from or args.date_to:
        filters = replace(
            filters,
            date_from=_parse_date(args.date_from),
            date_to=_parse_date(args.date_to),
        )
    return filters


def _parse_date(value: str | None):
    from datetime import datetime

    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise SystemExit(f"Not a valid date: {value!r}. Use YYYY-MM-DD.") from None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.gui:
        from .app import main as app_main

        return app_main([args.folder])

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        print(f"Not a folder: {folder}", file=sys.stderr)
        return 1

    if not find_exiftool():
        print(
            f"exiftool is required to read photo metadata.\nInstall it with:\n    "
            f"{install_hint()}\n",
            file=sys.stderr,
        )
        return 1

    from .core.db import init_db

    db_path = folder / "photo_stats.db"
    init_db(db_path)

    if args.import_legacy:
        return _import_legacy(db_path, folder)

    if not args.no_scan or args.reindex:
        if args.reindex:
            db_path.unlink(missing_ok=True)
            init_db(db_path)
        result = Indexer(db_path, folder).run()
        if not result.ok:
            print(result.message or "Scan failed", file=sys.stderr)
            return 1
        if not args.stats and not args.csv and not args.json:
            print(result.summary)

    with PhotoStore(db_path) as store:
        filters = filters_from_args(args)
        if args.stats or not (args.csv or args.json):
            print(export.to_text(store, filters), end="")
        if args.csv:
            Path(args.csv).write_text(export.to_csv(store, filters), encoding="utf-8")
            print(f"Saved {args.csv}")
        if args.json:
            Path(args.json).write_text(export.to_json(store, filters), encoding="utf-8")
            print(f"Saved {args.json}")
    return 0


def _import_legacy(db_path: Path, folder: Path) -> int:
    legacy = legacy_candidates(folder)
    if not legacy:
        print("No cache from the original script was found.", file=sys.stderr)
        return 1
    from .core.db import connect

    conn = connect(db_path)
    try:
        report = import_legacy_cache(legacy, conn, folder)
    finally:
        conn.close()
    print(report.summary() if not report.error else report.error, file=sys.stderr if report.error else sys.stdout)
    return 1 if report.error else 0


if __name__ == "__main__":
    sys.exit(main())
