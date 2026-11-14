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

# The build now uses MSVC (see build_native.sh), which links the C++ runtime dynamically
# rather than statically, so the target machine needs the Visual C++ Redistributable.
# Bundled here and installed silently so the end user never has to do anything — Windows
# will show its own one-time elevation (UAC) prompt specifically for this step, since
# installing a system runtime genuinely requires it, even though the rest of this
# installer deliberately runs without admin rights (PrivilegesRequired=lowest below).
# Cached in build/work so it's only downloaded once, not on every build.
redist="$ROOT/build/work/vc_redist.x64.exe"
mkdir -p "$ROOT/build/work"
if [ ! -f "$redist" ]; then
  info "downloading the VC++ Redistributable (one-time, ~25 MB)"
  curl -fL "https://aka.ms/vs/17/release/vc_redist.x64.exe" -o "$redist" \
    || die "could not download the VC++ Redistributable"
fi

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
Source: "$(cygpath -w "$redist")"; DestDir: "{tmp}"; Flags: dontcopy
[Icons]
Name: "{group}\\Jarvis Ultron"; Filename: "{app}\\JarvisUltron.exe"
Name: "{userdesktop}\\Jarvis Ultron"; Filename: "{app}\\JarvisUltron.exe"
Name: "{group}\\Uninstall Jarvis Ultron"; Filename: "{uninstallexe}"
[Run]
Filename: "{tmp}\\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; \\
    StatusMsg: "Installing the Visual C++ Runtime (one-time)..."; Check: VCRedistNeeded; Flags: waituntilterminated
Filename: "{app}\\JarvisUltron.exe"; Description: "Launch Jarvis Ultron now"; Flags: nowait postinstall skipifsilent
[Code]
function VCRedistNeeded(): Boolean;
var
  installed: Cardinal;
begin
  // Standard Microsoft-documented key for the VC++ 2015-2022 x64 runtime. If this key is
  // missing or Installed<>1, the runtime either isn't there or is too old — install it.
  // If it's already present, this returns False and Setup skips the step (and the UAC
  // prompt) entirely rather than re-running it on every install.
  if not RegQueryDWordValue(HKLM64, 'SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\X64', 'Installed', installed) then
    Result := True
  else
    Result := (installed <> 1);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // "Flags: dontcopy" above bundles vc_redist.x64.exe inside Setup.exe but does not
  // auto-extract it — this pulls it into {tmp} only when it's actually going to be
  // needed, right before the [Run] section runs it.
  if (CurStep = ssInstall) and VCRedistNeeded() then
    ExtractTemporaryFile('vc_redist.x64.exe');
end;
ISS
"$ISCC" "$(cygpath -w "$ROOT/build/work/jarvis.iss")" > "$ROOT/build/work/iscc.log" 2>&1 \
  || { tail -30 "$ROOT/build/work/iscc.log"; die "Inno Setup failed (see build/work/iscc.log)"; }
ok "installer: dist/JarvisUltron-Setup.exe"
echo "That single file is everything the user runs. It installs to %LocalAppData%\\JarvisUltron,"
echo "puts JarvisUltron.exe + a desktop/start-menu shortcut, and nothing else to click."
