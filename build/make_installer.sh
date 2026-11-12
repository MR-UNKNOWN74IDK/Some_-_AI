#!/usr/bin/env bash
# Wraps a compiled build into ONE self-installing Setup.exe (Inno Setup 6, https://jrsoftware.org).
# The installer creates the install folder itself and copies every file there; the user only ever
# double-clicks JarvisUltron.exe (Desktop + Start Menu shortcuts point at it, nothing else is exposed).
set -euo pipefail
source "$ROOT/build/lib.sh"
is_windows || die "Windows only"
ISCC="${ISCC:-}"
[ -n "$ISCC" ] || for c in "/c/Program Files (x86)/Inno Setup 6/ISCC.exe" "/c/Program Files/Inno Setup 6/ISCC.exe" iscc; do
  command -v "$c" >/dev/null 2>&1 && { ISCC="$c"; break; }
  [ -f "$c" ] && { ISCC="$c"; break; }
done
[ -n "$ISCC" ] || die "Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php"

src="${1:-}"
if [ -z "$src" ]; then
  [ -f "$ROOT/build/work/last_native_dir.txt" ] && src="$(cut -d= -f2 "$ROOT/build/work/last_native_dir.txt")"
fi
[ -n "$src" ] && [ -f "$src/JarvisUltron.exe" ] || die "no compiled build found — run ./jarvis.sh build first"
# Belt and suspenders: strip any stray doc markdown before packaging, keep SKILL.md (runtime data).
find "$src" -iname "*.md" ! -path "$src/skills/*/SKILL.md" -delete 2>/dev/null || true

ver="$(date +%Y.%m.%d)"
mkdir -p "$ROOT/build/work" "$ROOT/dist"
cat > "$ROOT/build/work/jarvis.iss" <<ISS
[Setup]
AppName=Jarvis Ultron
AppVersion=$ver
AppPublisher=Private
DefaultDirName={localappdata}\\JarvisUltron
DefaultGroupName=Jarvis Ultron
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=$(cygpath -w "$ROOT/dist")
OutputBaseFilename=JarvisUltron-Setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=Jarvis Ultron
WizardStyle=modern
[Files]
Source: "$(cygpath -w "$src")\\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
[Icons]
Name: "{group}\\Jarvis Ultron"; Filename: "{app}\\JarvisUltron.exe"
Name: "{userdesktop}\\Jarvis Ultron"; Filename: "{app}\\JarvisUltron.exe"
Name: "{group}\\Uninstall Jarvis Ultron"; Filename: "{uninstallexe}"
[Run]
Filename: "{app}\\JarvisUltron.exe"; Description: "Launch Jarvis Ultron now"; Flags: nowait postinstall skipifsilent
ISS
"$ISCC" "$(cygpath -w "$ROOT/build/work/jarvis.iss")" > "$ROOT/build/work/iscc.log" 2>&1 \
  || { tail -30 "$ROOT/build/work/iscc.log"; die "Inno Setup failed (see build/work/iscc.log)"; }
ok "installer: dist/JarvisUltron-Setup.exe"
echo "That single file is everything the user runs. It installs to %LocalAppData%\\JarvisUltron,"
echo "puts JarvisUltron.exe + a desktop/start-menu shortcut, and nothing else to click."
