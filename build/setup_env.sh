#!/usr/bin/env bash
set -euo pipefail
source "$ROOT/build/lib.sh"
is_windows || warn "Not on Windows: PyAudio/pycaw/comtypes will fail to install here."
py="$(find_python)" || die "Python 3.12 required"
[ -d "$ROOT/.venv" ] || { info "creating .venv"; $py -m venv "$ROOT/.venv"; }
vp="$(venv_python)"
"$vp" -m pip install --upgrade pip wheel -q
info "installing requirements (a few minutes)"
"$vp" -m pip install -r "$ROOT/requirements.txt" -q
"$vp" -m pip install pyinstaller cryptography keyring fastapi "uvicorn[standard]" pytest -q
ok "environment ready"
