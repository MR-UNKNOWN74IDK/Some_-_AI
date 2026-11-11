"""
core/console_guard.py — keeps the console quiet and writes a real log.

Problem seen in the field: when something was misconfigured (no API key, no
network) the app retried forever and printed a full traceback every few
seconds, flooding the CMD window.  This wrapper:

  * collapses identical consecutive lines ("... repeated 40 more times"),
  * caps output at MAX_LINES_PER_SEC so a runaway loop cannot flood the window,
  * mirrors everything (un-throttled, secrets redacted) to logs/app.log,
  * gives a windowed exe (where sys.stdout is None) a working stdout.
"""
from __future__ import annotations

import io
import os
import re
import sys
import threading
import time
from pathlib import Path

MAX_LINES_PER_SEC = 40
_SECRET = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|sk-[A-Za-z0-9_\-]{16,}|xox[bp]-[A-Za-z0-9\-]{10,})")


class _Guard(io.TextIOBase):
    def __init__(self, console, logfile):
        self._console, self._log = console, logfile
        self._buf = ""
        self._last, self._dups = None, 0
        self._win_start, self._win_n, self._dropped = time.monotonic(), 0, 0
        self._lock = threading.RLock()

    def writable(self):
        return True

    @property
    def encoding(self):
        return "utf-8"

    def write(self, s):
        if not isinstance(s, str):
            s = str(s)
        with self._lock:
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                self._emit(line)
        return len(s)

    def _to_log(self, line):
        if self._log:
            try:
                self._log.write(_SECRET.sub("[redacted]", line) + "\n")
            except Exception:
                pass

    def _to_console(self, line):
        if self._console:
            try:
                self._console.write(line + "\n")
            except Exception:
                pass

    def _emit(self, line):
        self._to_log(line)
        if line == self._last:
            self._dups += 1
            return
        if self._dups:
            self._to_console(f"   ... previous line repeated {self._dups} more time(s) (see logs/app.log)")
            self._dups = 0
        self._last = line
        now = time.monotonic()
        if now - self._win_start >= 1.0:
            if self._dropped:
                self._to_console(f"   ... {self._dropped} line(s) hidden to avoid flooding (see logs/app.log)")
            self._win_start, self._win_n, self._dropped = now, 0, 0
        self._win_n += 1
        if self._win_n > MAX_LINES_PER_SEC:
            self._dropped += 1
            return
        self._to_console(line)

    def flush(self):
        for h in (self._console, self._log):
            try:
                if h:
                    h.flush()
            except Exception:
                pass

    def isatty(self):
        return False

    def fileno(self):
        raise io.UnsupportedOperation("fileno")


def install() -> Path | None:
    if getattr(sys, "_console_guard", False):
        return None
    try:
        from core.user_paths import get_user_data_dir
        d = get_user_data_dir() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        path = d / "app.log"
        if path.exists() and path.stat().st_size > 3_000_000:
            path.replace(d / "app.1.log")
        logfile = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
        logfile.write(f"\n===== start {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    except Exception:
        path, logfile = None, None
    sys.stdout = _Guard(sys.__stdout__, logfile)
    sys.stderr = _Guard(sys.__stderr__, logfile)
    sys._console_guard = True
    return path
