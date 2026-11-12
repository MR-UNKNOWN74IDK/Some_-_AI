#!/usr/bin/env bash
# Zips the last compiled build as unzip-and-run, no installer. Secondary option; the
# single Setup.exe from ./jarvis.sh build is the normal way to hand this to yourself.
set -euo pipefail
source "$ROOT/build/lib.sh"
[ -f "$ROOT/build/work/last_native_dir.txt" ] || die "build first: ./jarvis.sh build"
src="$(cut -d= -f2 "$ROOT/build/work/last_native_dir.txt")"
[ -f "$src/JarvisUltron.exe" ] || die "build first: ./jarvis.sh build"
out="$ROOT/dist/JarvisUltron-Portable"
rm -rf "$out"; mkdir -p "$out"
cp -r "$src" "$out/app"
printf '@echo off\r\ncd /d "%%~dp0app"\r\nstart "" JarvisUltron.exe\r\n' > "$out/Start-Jarvis.cmd"
printf 'Logs and encrypted keys live in %%LOCALAPPDATA%%\\JarvisAI of the Windows user who runs this.\r\n' > "$out/README.txt"
(cd "$ROOT/dist" && powershell -NoProfile -Command "Compress-Archive -Force JarvisUltron-Portable JarvisUltron-Portable.zip") 2>/dev/null || true
ok "portable: dist/JarvisUltron-Portable (and .zip)"
