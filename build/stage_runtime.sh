#!/usr/bin/env bash
# Puts an embeddable CPython + pip next to the exe so forged skills can be tested/installed.
set -euo pipefail
source "$ROOT/build/lib.sh"
dest="$1"; rt="$dest/runtime/py"
mkdir -p "$rt"
zip="$ROOT/build/work/python-embed.zip"
mkdir -p "$ROOT/build/work"
url="https://www.python.org/ftp/python/$PY_EMBED_VERSION/python-$PY_EMBED_VERSION-embed-amd64.zip"
[ -f "$zip" ] || { info "downloading $url"; curl -fL "$url" -o "$zip"; }
unzip -qo "$zip" -d "$rt"
pth="$(ls "$rt"/python3*._pth | head -1)"
# enable site-packages + import site
sed -i 's/^#\s*import site/import site/' "$pth"
grep -q 'Lib/site-packages' "$pth" || printf 'Lib/site-packages\n' >> "$pth"
mkdir -p "$rt/Lib/site-packages"
gp="$ROOT/build/work/get-pip.py"
[ -f "$gp" ] || curl -fL https://bootstrap.pypa.io/get-pip.py -o "$gp"
"$rt/python.exe" "$gp" --no-warn-script-location -q
# common dependencies forged skills reach for (pure-Python or abi3 wheels)
"$rt/python.exe" -m pip install -q requests beautifulsoup4 psutil python-dateutil
ok "skill runtime staged at $rt"
