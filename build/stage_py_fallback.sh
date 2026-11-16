#!/usr/bin/env bash
# Copies the real, unmodified source of packages excluded from Nuitka compilation
# (see --nofollow-import-to in build_native.sh) into the compiled app's folder, so
# Python's normal import system finds them there at runtime — exactly as if they'd
# been pip-installed normally, never touched by Nuitka's Python-to-C compiler.
#
# This matters for `google` specifically: it's a namespace package (no single real
# __init__.py), so having google.generativeai/google.protobuf compiled by Nuitka while
# google.genai lives here as plain files is the normal, supported way namespace packages
# work across multiple locations on sys.path — not a conflict.
set -euo pipefail
source "$ROOT/build/lib.sh"
dist="$1"
vp="$(venv_python)" || die "run ./jarvis.sh setup first"

dest="$dist/_py_fallback"
mkdir -p "$dest"

genai_dir="$("$vp" -c "import google.genai, os; print(os.path.dirname(google.genai.__file__))")"
[ -d "$genai_dir" ] || die "google.genai package directory not found — is it installed in .venv?"
mkdir -p "$dest/google"
cp -r "$genai_dir" "$dest/google/genai"

pw_dir="$("$vp" -c "import playwright, os; print(os.path.dirname(playwright.__file__))")"
[ -d "$pw_dir" ] || die "playwright not found — is it installed in .venv?"
cp -r "$pw_dir" "$dest/playwright"

# Strip bytecode caches and test folders — not needed at runtime, just takes up space.
find "$dest" -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "$dest" -type d -iname "tests" -prune -exec rm -rf {} + 2>/dev/null || true

ok "staged real source for google.genai and playwright at $dest"
