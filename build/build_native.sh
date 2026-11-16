#!/usr/bin/env bash
# Compiles the Python source to C and then to native machine code (Nuitka) — no .py/.pyc is
# shipped, so the source is not readable the way a PyInstaller bundle's bytecode is.
# Needs a C compiler; Nuitka downloads MinGW64 itself on first run.
set -euo pipefail
source "$ROOT/build/lib.sh"
is_windows || die "Windows only"
vp="$(venv_python)" || die "run ./jarvis.sh setup first"
cd "$ROOT"

info "1/3 tests"
"$vp" -m pytest tests -q -x || die "tests failed — not building"

info "2/3 installing compiler toolchain (first run only)"
"$vp" -m pip install -q nuitka ordered-set zstandard

out="build/work/native"
rm -rf "$out"
info "3/3 compiling to native code (30-90 min the first time, faster after)"
# Back on MinGW (not MSVC): MSVC was tried as a fix for the memory crash below and hit the
# SAME wall on the SAME file, just with MSVC's own wording ("compiler is out of heap space
# in pass 2") — proving this was never a MinGW-specific weakness, it's that one particular
# auto-generated file is too large for either compiler on a free-tier machine's RAM. MinGW
# is back because it statically links the C++ runtime (no Visual C++ Redistributable needed
# on the target machine — see README_ULTRA.md), which MSVC did not get us anything for.
#
# The actual fix: google-genai's types.py (23,745 lines, auto-generated from its data
# models) is what crashed both compilers. Its two largest siblings in the same package
# (models.py, _live_converters.py) are large enough to be a real risk too once types.py is
# out of the way. Playwright's auto-generated API files (sync_api/_generated.py,
# async_api/_generated.py) are comparably huge and Playwright is actively used for browser
# automation, so excluding it proactively here, not reactively after a second failure.
#
# --nofollow-import-to=google.genai,playwright below tells Nuitka not to compile either
# package to C at all; build/stage_py_fallback.sh (called after this compile) copies their
# real, unmodified source onto disk next to the exe instead, and core's frozen-app bootstrap
# (main.py) adds that folder to sys.path so Python's normal import system finds them there —
# exactly as they would run from a normal pip install, never touched by Nuitka. This only
# affects these two specific third-party libraries (whose source is public on PyPI regardless
# of how this app ships) — none of Jarvis/Ultron's own code is affected; it stays compiled.
# If some other huge auto-generated file in a different dependency trips the same wall later,
# the fix is the same: add it here, and to the copy list in build/stage_py_fallback.sh.
#
# --low-memory/--lto=no/--jobs=1 are kept as an extra safety margin on top of the above, in
# case some other file not caught by the scan above still needs the memory headroom.
# Windows metadata below is cosmetic (Properties -> Details tab) but also makes the exe
# look like a normal signed-looking app rather than an anonymous binary to SmartScreen/AV
# heuristics, which somewhat reduces (never eliminates) false-flagging on another PC.
"$vp" -m nuitka --standalone --assume-yes-for-downloads --mingw64 --low-memory --lto=no --jobs=1 \
  --nofollow-import-to=google.genai --nofollow-import-to=playwright \
  --enable-plugin=pyqt6 --windows-console-mode=disable \
  --windows-icon-from-ico=assets/jarvis_logo.ico \
  --company-name="Jarvis Ultron (private build)" --product-name="Jarvis Ultron" \
  --file-version=1.0.0.0 --product-version=1.0.0.0 \
  --file-description="Jarvis Ultron" \
  --output-dir="$out" --output-filename=JarvisUltron.exe \
  --include-package=core --include-package=actions --include-package=agent --include-package=memory \
  --include-package=jarvis_connect --include-package=dashboard --include-package=smart_home \
  --include-module=ultra_control_center --include-module=workspace_store \
  --include-data-dir=assets=assets --include-data-dir=config=config --include-data-dir=features=features \
  --include-data-dir=skills=skills --include-data-dir=plugins=plugins --include-data-dir=dashboard/static=dashboard/static \
  --include-data-files=version.txt=version.txt --include-data-files=requirements.txt=requirements.txt \
  --nofollow-import-to=tests \
  main.py

d="$out/main.dist"
[ -f "$d/JarvisUltron.exe" ] || die "no exe produced"
for f in api_keys.json email_credentials.json secrets.bin discord_bot.json spotify-config.json; do
  find "$d" -name "$f" | grep -q . && die "credential file found in compiled output: $f"
done
# Anything plain-text on purpose stays plain text; everything else here is now compiled, not source.
find "$d" -maxdepth 1 \( -name "*.py" -o -name "*.pyc" \) -delete 2>/dev/null || true
# Developer/user-info docs (README, SECURITY, TRADEMARK...) never ship. skills/*/SKILL.md is kept:
# it is read by core/skills_engine.py at runtime, it is not documentation.
find "$d" -iname "*.md" ! -path "$d/skills/*/SKILL.md" -delete 2>/dev/null || true

bash build/stage_py_fallback.sh "$ROOT/$d"
bash build/stage_runtime.sh "$ROOT/$d"
bash build/strip_symbols.sh "$ROOT/$d"
ok "compiled: $d/JarvisUltron.exe"
echo "DIST_DIR=$d" > build/work/last_native_dir.txt
