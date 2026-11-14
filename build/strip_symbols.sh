#!/usr/bin/env bash
# Strips debug symbol tables from the compiled exe/dll/pyd files, IF building with the
# MinGW engine (which uses the `strip` tool Nuitka downloads alongside it). With the MSVC
# engine (the current default, see build_native.sh) this step is normally a no-op and
# that's fine, not a failure: MSVC puts debug symbols in separate .pdb files rather than
# embedding them in the exe/dll at all, and Nuitka's default release build doesn't
# generate .pdb files for a standalone build in the first place — so there is typically
# nothing embedded to strip either way. Does NOT remove plain text strings baked into the
# binary (e.g. a build-path string) — only a symbol table, and only when one exists.
set -uo pipefail
source "$ROOT/build/lib.sh"
dir="$1"
[ -d "$dir" ] || { warn "strip: $dir not found, skipping"; exit 0; }

strip_exe=""
for base in "$LOCALAPPDATA/Nuitka/Nuitka/Cache" "$APPDATA/Nuitka/Nuitka" "$HOME/AppData/Local/Nuitka/Nuitka"; do
  [ -d "$base" ] || continue
  found="$(find "$base" -iname "strip.exe" 2>/dev/null | head -1)"
  [ -n "$found" ] && { strip_exe="$found"; break; }
done
if [ -z "$strip_exe" ]; then
  info "no MinGW strip.exe found — expected with the MSVC engine (symbols aren't embedded in the first place), skipping"
  exit 0
fi
info "stripping debug symbols with $strip_exe"
count=0
while IFS= read -r -d '' f; do
  "$strip_exe" --strip-unneeded "$f" 2>/dev/null && count=$((count + 1))
done < <(find "$dir" \( -iname "*.exe" -o -iname "*.dll" -o -iname "*.pyd" \) -print0)
ok "stripped symbols from $count file(s)"
