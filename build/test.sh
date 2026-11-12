#!/usr/bin/env bash
set -euo pipefail
source "$ROOT/build/lib.sh"
vp="$(venv_python)" || die "run ./jarvis.sh setup first"
cd "$ROOT"
"$vp" -m pytest tests -q "$@"
