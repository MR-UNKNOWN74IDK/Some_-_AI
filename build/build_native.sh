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
# Switched from MinGW to MSVC (Visual Studio's own compiler, preinstalled on GitHub's
# windows-latest runners) after MinGW kept running out of memory on one specific
# auto-generated file (google-genai's types.py) even with --low-memory, --lto=no and
# --jobs=1 all applied together — MSVC builds its internal representation of a large file
# differently and does not hit the same wall. Trade-off: MSVC links the C++ runtime
# dynamically rather than statically, so the target machine now needs the Visual C++
# Redistributable installed — build/make_installer.sh bundles and silently installs it,
# so this is handled automatically and nothing the end user has to do themselves.
# --low-memory alone (serializing compilation instead of running it across all CPU cores)
# was NOT enough: google-genai's auto-generated C file (module.google.genai.types.c) is
# large enough to exhaust RAM even compiled by itself, with --low-memory already applied
# (confirmed from an actual failed run: same "cc1.exe: out of memory" on the same file).
# --lto=no additionally turns off link-time whole-program optimization, which is by far the
# most memory-hungry part of compiling a single large file like this one; --jobs=1 pins
# parallelism to one file at a time explicitly, rather than relying on --low-memory's
# implicit choice of how many to run at once. Together these should fit the free-tier
# runner's RAM. None of this changes what the compiled app does at runtime, only how much
# memory compiling it needs; it costs real build time, which is why the workflow's timeout
# was raised to match.
# Windows metadata below is cosmetic (Properties -> Details tab) but also makes the exe
# look like a normal signed-looking app rather than an anonymous binary to SmartScreen/AV
# heuristics, which somewhat reduces (never eliminates) false-flagging on another PC.
"$vp" -m nuitka --standalone --assume-yes-for-downloads --low-memory --lto=no --jobs=1 \
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

bash build/stage_runtime.sh "$ROOT/$d"
bash build/strip_symbols.sh "$ROOT/$d"
ok "compiled: $d/JarvisUltron.exe"
echo "DIST_DIR=$d" > build/work/last_native_dir.txt
