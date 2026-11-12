#!/usr/bin/env bash
set -uo pipefail
source "$ROOT/build/lib.sh"
fail=0
is_windows && ok "Windows shell detected" || { warn "not Windows — you can run tests but cannot produce the .exe"; }
if py="$(find_python)"; then ok "Python 3.12 found ($py)"; else warn "Python 3.12 not found (python.org installer, tick 'Add to PATH')"; fail=1; fi
for t in curl unzip; do command -v $t >/dev/null && ok "$t" || { warn "$t missing"; fail=1; }; done
command -v iscc >/dev/null && ok "Inno Setup (optional installer)" || info "Inno Setup not found (optional)"
if is_windows && command -v wmic >/dev/null 2>&1; then
  arch="$(wmic os get osarchitecture 2>/dev/null | tr -d '\r' | sed -n 2p | xargs)"
  ver="$(wmic os get caption 2>/dev/null | tr -d '\r' | sed -n 2p | xargs)"
  [ "$arch" = "64-bit" ] && ok "build machine: $ver, $arch" \
    || warn "build machine reports $arch — a 32-bit build machine cannot produce a working x86-64 app"
fi
[ -d "$ROOT/.venv" ] && ok ".venv exists" || info ".venv not created yet"
exit $fail
