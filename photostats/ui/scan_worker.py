"""Runs the indexer on a worker thread and re-emits its progress as signals.

Qt only lives here: the engine itself is plain Python so it stays testable and
usable from the command line.

The legacy-cache prompt is *not* handled here: the main window checks for one
before starting this worker, so the thread never has to block waiting for a
dialog answer.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.config import AppConfig
from ..core.indexer import Indexer


class ScanWorker(QThread):
    """Scans a library in the background."""

    progress = Signal(object)       # Progress
    finished_scan = Signal(object)  # IndexResult
    log = Signal(str)

    def __init__(self, db_path: Path, root: Path, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.root = Path(root)
        self.config = config
        self._indexer: Indexer | None = None

    def run(self) -> None:  # noqa: D102 - Qt entry point
        from ..core.indexer import Indexer, IndexResult

        result = IndexResult()
        try:
            self._indexer = Indexer(
                self.db_path,
                self.root,
                exiftool_path=self.config.exiftool_path or None,
                workers=self.config.workers,
                batch=self.config.batch_size,
                on_progress=self.progress.emit,
                on_log=self.log.emit,
            )
            result = self._indexer.run()
        except Exception as exc:  # a dead thread must still answer the window
            self.log(f"the scan failed: {exc}")
            result.message = str(exc)
            result.ok = False
        self.finished_scan.emit(result)

    def cancel(self) -> None:
        if self._indexer is not None:
            self._indexer.cancel()


class LegacyImportWorker(QThread):
    """Copies rows from the original script's cache, reporting progress."""

    progress = Signal(int)
    finished_import = Signal(object)  # ImportReport

    def __init__(self, legacy_path: Path, db_path: Path, root: Path, parent=None) -> None:
        super().__init__(parent)
        self.legacy_path = Path(legacy_path)
        self.db_path = Path(db_path)
        self.root = Path(root)
        self._indexer = None

    def run(self) -> None:  # noqa: D102 - Qt entry point
        from ..core import db as dbmod
        from ..core.legacy import ImportReport, import_legacy_cache

        report = ImportReport()
        try:
            dbmod.init_db(self.db_path)
            conn = dbmod.connect(self.db_path)
            try:
                report = import_legacy_cache(
                    self.legacy_path, conn, self.root, on_progress=self.progress.emit
                )
            finally:
                conn.close()
        except Exception as exc:  # a dead thread must still answer the window
            report = ImportReport(error=str(exc))
        self.finished_import.emit(report)

    def cancel(self) -> None:
        pass
