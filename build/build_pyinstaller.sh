#!/usr/bin/env bash
# Fallback engine: PyInstaller (bytecode bundle, no C compiler needed). Use only if
# ./jarvis.sh build (Nuitka) fails on your machine. Less opaque than the native build.
set -euo pipefail
source "$ROOT/build/lib.sh"
is_windows || die "Windows only"
runtime=1
for a in "$@"; do case "$a" in --no-skill-runtime) runtime=0;; esac; done
vp="$(venv_python)" || die "run ./jarvis.sh setup first"
cd "$ROOT"

info "1/4 tests"
"$vp" -m pytest tests -q -x || die "tests failed — not building"

info "2/4 generating PyInstaller spec"
mkdir -p build/work
sed -e "s/name='Jarvis'/name='JarvisUltron'/g" \
    -e "s/'pyaudio', 'numpy'/'pyaudio', 'numpy', 'cryptography', 'keyring', 'ultra_control_center', 'core.secrets_store', 'core.safety_stack', 'core.modes', 'core.lan_policy', 'core.skill_runtime', 'core.mode_router'/" \
    -e "s#assets/Jarvis_Lite_Logo.ico#assets/jarvis_logo.ico#g" \
    installer/Jarvis.spec > build/work/JarvisUltron.spec
sed -i "s#(os.path.join(cwd, 'workspace_store.py'), '.'),#(os.path.join(cwd, 'workspace_store.py'), '.'),\n        (os.path.join(cwd, 'ultra_control_center.py'), '.'),\n        (os.path.join(cwd, 'config', 'jarvis_connect.default.json'), 'config'),#" build/work/JarvisUltron.spec
[ -f assets/jarvis_logo.ico ] || sed -i "s#assets/jarvis_logo.ico#assets/Jarvis_Lite_Logo.ico#g" build/work/JarvisUltron.spec

info "3/4 PyInstaller (several minutes)"
"$vp" -m PyInstaller --noconfirm --clean --distpath build/work/pyi_dist --workpath build/work/pyi build/work/JarvisUltron.spec

out="build/work/pyi_dist/JarvisUltron"
[ -f "$out/JarvisUltron.exe" ] || die "exe not produced"
if [ "$runtime" = 1 ]; then info "4/4 skill runtime"; bash build/stage_runtime.sh "$ROOT/$out"
else warn "4/4 skipped: skill forging/testing unavailable in this build"; fi
if find "$out" \( -name 'api_keys.json' -o -name 'email_credentials.json' -o -name 'secrets.bin' \) | grep -q .; then
  die "credential file found in dist — aborting"
fi
# Developer/user-info docs never ship; skills/*/SKILL.md is kept (read at runtime, not documentation).
find "$out" -iname "*.md" ! -path "$out/skills/*/SKILL.md" -delete 2>/dev/null || true
bash build/strip_symbols.sh "$ROOT/$out"
echo "DIST_DIR=$out" > build/work/last_native_dir.txt
ok "built (fallback engine): $out/JarvisUltron.exe"
echo "Run ./jarvis.sh package installer to wrap this into one Setup.exe."
