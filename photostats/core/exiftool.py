"""Driver for the external exiftool binary.

Keeps one ``exiftool -stay_open`` process per worker instead of spawning a new
process for every batch, which is what makes scanning a large library fast.
Commands are fed through stdin and each one's output is delimited by the
``{ready}`` line exiftool writes when it finishes, which is reliable on all
platforms. A reader thread plus a queue gives us a real timeout instead of
blocking forever on a wedged process.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .parse import EXIFTAGS

READY = "{ready}"
DEFAULT_TIMEOUT = 180.0
STDERR_KEEP = 4096

#: exiftool command line shared by every read. ``#`` suppresses print conversion
#: so numeric tags come back as numbers while Flash/WhiteBalance stay readable.
EXIFTAG_ARGS = [
    *[f"-{tag}" for tag in EXIFTAGS],
    "-api",
    "largefilesupport=1",
    "-charset",
    "filename=UTF8",
]

def _reject_quiet(args: list[str]) -> None:
    """Guard against the ``-q`` / ``-stay_open`` interaction.

    In ``-stay_open`` mode exiftool prints a ``{ready}`` line after every command,
    which is how we know the output is complete. Passing ``-q`` makes it suppress
    that marker as well, so the reader would block until the timeout on every
    call. Never add ``-q`` to the arguments.
    """
    for arg in args:
        if arg == "-q" or arg.startswith("-q "):
            raise ExifToolError(
                "internal error: -q cannot be used with -stay_open (it suppresses the "
                "{ready} marker)"
            )


INSTALL_HINTS = {
    "darwin": "brew install exiftool",
    "win32": "Download exiftool.exe from https://exiftool.org and place it in your PATH",
    "linux": "sudo apt install libimage-exiftool-perl  (or: sudo dnf install perl-Image-ExifTool)",
}


class ExifToolError(RuntimeError):
    """exiftool is missing, unreadable, or failed in a way we cannot recover."""


def resource_dir() -> Path:
    """Directory holding bundled binaries (PyInstaller onefile/onedir aware)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def find_exiftool(explicit: str | os.PathLike[str] | None = None) -> str | None:
    """Locate the binary: explicit path, env var, bundled copy, then PATH."""
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return str(candidate)
        return None
    env = os.environ.get("PHOTOSTATS_EXIFTOOL")
    if env and Path(env).is_file():
        return env
    bundled = resource_dir() / ("exiftool.exe" if sys.platform == "win32" else "exiftool")
    if bundled.is_file():
        return str(bundled)
    return shutil.which("exiftool")


def install_hint() -> str:
    return INSTALL_HINTS.get(sys.platform, "See https://exiftool.org for install instructions")


def exiftool_version(executable: str) -> str:
    try:
        result = subprocess.run(
            [executable, "-ver"], capture_output=True, text=True, timeout=30, check=False
        )
        return result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


class ExifTool:
    """A persistent exiftool process driven by one thread at a time."""

    def __init__(self, executable: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.executable = executable
        self.timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._out: queue.Queue = queue.Queue()
        self._err: queue.Queue = queue.Queue()
        self._readers: list[threading.Thread] = []
        self._stderr_tail: list[str] = []
        self._broken = False

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        self._broken = False
        self._stderr_tail.clear()
        try:
            self._proc = subprocess.Popen(
                [self.executable, "-stay_open", "True", "-@", "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            self._proc = None
            raise ExifToolError(f"could not start exiftool: {exc}") from exc
        self._readers = [
            threading.Thread(target=self._pump, args=(self._proc.stdout, self._out), daemon=True),
            threading.Thread(target=self._pump, args=(self._proc.stderr, self._err), daemon=True),
        ]
        for thread in self._readers:
            thread.start()

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.write("-stay_open\nFalse\n")
                proc.stdin.flush()
                proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except (OSError, ValueError):
                pass

    def __enter__(self) -> ExifTool:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _pump(self, stream, sink: queue.Queue) -> None:
        try:
            for line in stream:
                sink.put(line)
        except (OSError, ValueError):
            pass
        finally:
            sink.put(None)

        # -- commands ------------------------------------------------------
    def execute(self, args: list[str]) -> str:
        """Run one exiftool command, return its stdout. Not thread-safe per call."""
        _reject_quiet(args)
        if self._broken:
            self.close()
            self.start()
        self.start()
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise ExifToolError("exiftool is not running")
        try:
            proc.stdin.write("\n".join(args) + "\n-execute\n")
            proc.stdin.flush()
        except (OSError, ValueError) as exc:
            self._fail(f"exiftool pipe broke: {exc}")
        return self._read_until_ready()

    def read_paths(self, paths: list[str]) -> list[dict]:
        """Read metadata for *paths*; one dict per file exiftool could read.

        Callers pair results with the requested paths using ``SourceFile``.
        """
        if not paths:
            return []
        raw = self.execute(["-j", *EXIFTAG_ARGS, *paths])
        if not raw.strip():
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # exiftool may print warnings ahead of the payload.
            start = raw.find("[")
            if start < 0:
                return []
            try:
                data = json.loads(raw[start:])
            except json.JSONDecodeError as exc:
                raise ExifToolError(f"could not parse exiftool output: {exc}") from exc
        return [item for item in data if isinstance(item, dict)]

    # -- internals ---------------------------------------------------------
    def _read_until_ready(self) -> str:
        lines: list[str] = []
        deadline = time.monotonic() + self.timeout
        while True:
            # Drain stderr as we go. Nothing else reads it until something goes
            # wrong, and exiftool writes a line per unreadable file — a library
            # with thousands of those was growing this queue unbounded, for the
            # whole scan, for nothing but a diagnostic nobody asked for.
            self._drain_stderr()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._fail(f"exiftool timed out after {self.timeout:.0f}s")
            try:
                line = self._out.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue
            if line is None:
                self._fail(f"exiftool exited unexpectedly {self._error_tail()}")
            if line.strip() == READY:
                return "".join(lines)
            lines.append(line)

    def _drain_stderr(self) -> None:
        while True:
            try:
                line = self._err.get_nowait()
            except queue.Empty:
                return
            if line is None:
                return
            self._stderr_tail.append(line)
            if len(self._stderr_tail) > 40:
                self._stderr_tail.pop(0)

    def _error_tail(self) -> str:
        self._drain_stderr()
        tail = "".join(self._stderr_tail).strip()
        return f": {tail[-STDERR_KEEP:]}" if tail else ""

    def _fail(self, message: str) -> None:
        self.close()
        self._broken = True
        raise ExifToolError(message)
