"""
core/skill_runtime.py — a real Python interpreter for forged skills.

In the compiled app `sys.executable` is JarvisUltron.exe, not python.exe, so
anything that does `subprocess.run([sys.executable, "-c", ...])` would start a
second copy of the whole assistant.  Skill sandbox tests and dependency
installs therefore use a small embeddable CPython that the build script
(build/stage_runtime.sh) places next to the executable:

    <install dir>/JarvisUltron.exe
    <install dir>/runtime/py/python.exe      <- this module finds it
    <install dir>/runtime/py/Lib/site-packages

When running from source (development) the current interpreter is used.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

DEV = "<dev>"
MISSING_MESSAGE = (
    "The skill runtime is not installed in this build, so I can't test or install new skills. "
    "Rebuild with './jarvis.sh build' (without --no-skill-runtime)."
)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def runtime_dir() -> Optional[Path]:
    if not is_frozen():
        return None
    return Path(sys.executable).resolve().parent / "runtime" / "py"


def python_executable() -> Optional[str]:
    """Interpreter path; DEV sentinel from source; None if frozen and missing."""
    if not is_frozen():
        return DEV
    rd = runtime_dir()
    exe = rd / "python.exe" if rd else None
    return str(exe) if exe and exe.exists() else None


def activate() -> None:
    """Let the frozen app import pure-Python packages that forged skills installed.
    Appended last so bundled modules always win."""
    rd = runtime_dir()
    if not rd:
        return
    sp = rd / "Lib" / "site-packages"
    if sp.is_dir() and str(sp) not in sys.path:
        sys.path.append(str(sp))
