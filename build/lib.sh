# shared helpers (sourced)
ok()   { printf '\033[32m[ok]\033[0m   %s\n' "$*"; }
info() { printf '\033[36m[..]\033[0m   %s\n' "$*"; }
warn() { printf '\033[33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

is_windows() { case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) return 0;; *) return 1;; esac; }

# Python 3.12 is pinned: the embedded skill runtime must match the interpreter PyInstaller bundles.
PY_MINOR="3.12"
PY_EMBED_VERSION="3.12.8"

find_python() {
  for c in "py -$PY_MINOR" "python3.12" "python"; do
    if $c -c "import sys;sys.exit(0 if sys.version_info[:2]==(3,12) else 1)" 2>/dev/null; then echo "$c"; return 0; fi
  done
  return 1
}

venv_python() {
  if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then echo "$ROOT/.venv/Scripts/python.exe"
  elif [ -x "$ROOT/.venv/bin/python" ]; then echo "$ROOT/.venv/bin/python"
  else return 1; fi
}

activate_venv() {
  # shellcheck disable=SC1091
  if [ -f "$ROOT/.venv/Scripts/activate" ]; then source "$ROOT/.venv/Scripts/activate"
  elif [ -f "$ROOT/.venv/bin/activate" ]; then source "$ROOT/.venv/bin/activate"
  else die "no .venv — run ./jarvis.sh setup first"; fi
}
