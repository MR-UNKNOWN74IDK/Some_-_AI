#!/usr/bin/env bash
# Jarvis Ultron — build & maintenance entry point (run from Git Bash on Windows 10/11).
#   ./jarvis.sh doctor              check prerequisites
#   ./jarvis.sh setup               create .venv and install dependencies
#   ./jarvis.sh test                run the test suite
#   ./jarvis.sh build [flags]       compile to native code and produce ONE installer:
#                                     dist/JarvisUltron-Setup.exe
#         --engine=pyinstaller      fallback if the native compiler fails on your machine
#         --no-skill-runtime        skip the embedded Python (skill forging disabled)
#         --no-installer            stop after compiling, skip the Inno Setup step
#   ./jarvis.sh package portable    also produce a zip (no installer, unzip-and-run) from the last build
#   ./jarvis.sh run                 start from source (development)
#   ./jarvis.sh clean
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ROOT
source "$ROOT/build/lib.sh"
cmd="${1:-help}"; shift || true
case "$cmd" in
  doctor) bash "$ROOT/build/doctor.sh" ;;
  setup)  bash "$ROOT/build/setup_env.sh" ;;
  test)   bash "$ROOT/build/test.sh" "$@" ;;
  build)
    engine="native"; no_installer=0; pass=()
    for a in "$@"; do case "$a" in
      --engine=pyinstaller) engine="pyinstaller" ;;
      --engine=native) engine="native" ;;
      --no-installer) no_installer=1 ;;
      *) pass+=("$a") ;;
    esac; done
    if [ "$engine" = "native" ]; then bash "$ROOT/build/build_native.sh" "${pass[@]:-}"
    else bash "$ROOT/build/build_pyinstaller.sh" "${pass[@]:-}"; fi
    [ "$no_installer" = 1 ] || bash "$ROOT/build/make_installer.sh"
    ;;
  package) case "${1:-}" in
             installer) bash "$ROOT/build/make_installer.sh" "${2:-}" ;;
             portable)  bash "$ROOT/build/make_portable.sh" ;;
             *) die "usage: ./jarvis.sh package installer|portable" ;;
           esac ;;
  run)    activate_venv; exec python "$ROOT/main.py" ;;
  clean)  rm -rf "$ROOT/build/work" "$ROOT/dist" "$ROOT/.pytest_cache"; ok "cleaned" ;;
  *)      sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
esac
