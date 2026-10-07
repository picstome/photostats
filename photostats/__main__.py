"""``python -m photostats`` launches the app."""

from __future__ import annotations

import multiprocessing
import sys

from .app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # required when frozen on Windows/macOS
    sys.exit(main())
