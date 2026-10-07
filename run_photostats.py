"""Entry point for the packaged app.

PyInstaller runs the entry script as ``__main__`` with no package context, so the
relative imports in ``photostats/__main__.py`` would fail inside a frozen build.
This wrapper is what the spec points at; ``python -m photostats`` still works for
running from a checkout.
"""

from __future__ import annotations

import multiprocessing
import sys

from photostats.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # required when frozen on Windows/macOS
    sys.exit(main())
