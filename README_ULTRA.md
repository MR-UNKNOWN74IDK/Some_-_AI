# Jarvis Ultron (private build)

Merge of Brahma Echo + Brahma Evo (Evo already contained all of Echo), renamed to **Jarvis** and **Ultron**.

## The two modes
| | Jarvis (default) | Ultron |
|---|---|---|
| Does | chat, explain, look things up (web, weather, memory, read files) | executes: apps, files, commands, devices, messages, skills, self-heal |
| Never | executes anything | makes conversation |

Asking a mode for the other kind of work does **not** run it. It notes your request, tells you, and waits:

* Jarvis: *"Jarvis, please open Spotify"* -> "I can't execute in Jarvis mode. Say 'Ultron, please open Spotify' or yes."
  * say **"switch to Ultron"** (or "yes") -> switches and runs *please open Spotify* right away
  * say **"Ultron, please open Spotify"** -> switches and runs it
* Ultron: *"what's the weather"* -> offers to switch to Jarvis, same flow in reverse.
* With nothing pending you can switch any time: "switch to Jarvis", "Ultron mode". "Aldron"/"Altron" (speech-to-text spellings) work too.
* Lockdown (Control Center) = Jarvis only, nothing can execute.

Enforcement: typed/mobile/dashboard commands are routed deterministically (`core/mode_router.py`); voice turns are enforced at the tool call, so Jarvis physically cannot run an action tool. "Ultron doesn't chat" on voice relies on its prompt plus refusing info tools; it is not as strict as the tool gate. The text classifier is keyword-based and can misjudge odd phrasing; say the mode name to override.

## Keys & settings
Settings -> Control Center. Keys are stored encrypted (Windows DPAPI, tied to your Windows login), not in any file.

## If the console keeps printing text
Fixed causes: the launcher reinstalled everything on every start and accepted any Python version; the reconnect loop printed a full traceback every 5 s when the API key/internet was missing. Now: Python 3.11/3.12 only, installs only when `requirements.txt` changes, reconnect backs off (5s -> 2min), repeated lines are collapsed, everything is logged to `%LOCALAPPDATA%\JarvisAI\logs\app.log` (setup output: `setup.log`). Debug run: `start_jarvis.bat console`.
Also disabled: auto-update from the original author's GitHub.

## Build — one installer, source compiled to native code
```
./jarvis.sh doctor
./jarvis.sh setup
./jarvis.sh build                 # -> dist/JarvisUltron-Setup.exe   (everything in one file)
```
`./jarvis.sh build` does all of it: runs the tests, compiles the Python source to C and then to
native machine code with Nuitka (no `.py`/`.pyc` is shipped — there is no source to open, only the
same kind of binary a C program would produce), stages the skill-forging runtime, and wraps the
result into **one** installer with Inno Setup 6 (https://jrsoftware.org/isdl.php — install that
first). Compiles with MSVC (Visual Studio's compiler), switched from MinGW after MinGW kept
running out of memory on one specific auto-generated file (google-genai's types.py) even at
its lowest-memory settings; GitHub's windows-latest runners have MSVC preinstalled, nothing
extra to download for that part.

Hand that one file, `JarvisUltron-Setup.exe`, to the Windows user. It is the whole deliverable:
double-clicking it creates the install folder under `%LocalAppData%\JarvisUltron`, copies every
compiled file there itself, and adds a Desktop/Start-Menu shortcut. The user only ever double-clicks
**one exe** — `JarvisUltron.exe` — never a raw folder of files.

What stays as plain text on purpose, and only this:
* `%LocalAppData%\JarvisAI\features\` — skills Jarvis/Ultron forges for itself (`.py`, so you can read
  what a forged skill does; the safety stack's hash check still runs on them)
* `%LocalAppData%\JarvisAI\config\app_settings.json` — your toggles (mode, safety layers, LAN access...)
* `%LocalAppData%\JarvisAI\logs\*.log` and the safety audit log

Everything else — the app itself — is compiled, and API keys are in the encrypted vault, never a file.

`build/strip_symbols.sh` strips debug symbol tables when building with the MinGW fallback engine
(see `--engine=pyinstaller` below). With the current MSVC engine this step is normally a no-op —
not a failure: MSVC keeps debug symbols in separate `.pdb` files rather than embedding them in the
exe/dll, and Nuitka's default release build doesn't generate `.pdb` files for a standalone build in
the first place, so there's typically nothing embedded to strip either way. Either way, this never
scrubs plain-text strings baked into the binary as data — it won't remove a build-path string;
build from a path that doesn't contain your Windows username if that matters to you.

Flags: `--no-skill-runtime` skips the embedded Python (skill forging then unavailable);
`--no-installer` stops after compiling, if you just want to inspect the compiled folder;
`--engine=pyinstaller` is a fallback bytecode build for if the native compile fails on your
machine (less opaque — see Limits). `./jarvis.sh package portable` additionally zips the compiled
folder with no installer. Keys are per Windows user: install and run as the same account.

## Building without a local Windows machine (or if Smart App Control blocks the build)
`.github/workflows/build.yml` builds this on **GitHub's own cloud Windows VM** instead of
yours — a free, standard, legitimate GitHub feature (Actions), not a third-party site. It
sidesteps a locally-enabled Smart App Control / Application Control policy entirely, since
the build happens on a disposable machine GitHub tears down afterward, not your PC.

1. Push this project to a **private** GitHub repository (the original LICENSE doesn't allow
   redistributing it publicly, so keep it private — this is just for your own CI use).
2. Repo's **Actions** tab -> "Build Jarvis Ultron" -> **Run workflow**.
3. Wait (usually 30-90 min) -> open the finished run -> **Artifacts** -> download
   `JarvisUltron-Setup` -> that's your installer.

**One real limitation:** the workflow builds with `--no-skill-runtime` by default, to keep
the job comfortably inside GitHub's free-tier time limit — meaning self-forged skills won't
work in that build. Remove that flag in the workflow file if you need skill forging and are
fine with a longer CI run. No API keys or personal data are involved in this; the vault is
created empty on whichever machine later launches the app, never baked into the build.

## Cross-machine compatibility (Windows 11 x86-64, and older)
What's actually done to make the compiled exe run on a Windows machine other than the one
that built it, and what's honestly not guaranteed:
* **Visual C++ Redistributable:** the build now uses MSVC (see above), which links the C++
  runtime dynamically rather than statically, so the target machine needs the Redistributable
  installed. `build/make_installer.sh` bundles it and installs it silently as part of Setup —
  the end user doesn't have to do anything, but Windows will show one UAC elevation prompt
  specifically for that step (genuinely required to install a system runtime), separate from
  the rest of the installer, which runs without admin rights. Skipped automatically on a
  machine that already has it, so this prompt won't reappear on every reinstall.
* **Not CPU-specific.** The heavy native dependencies (OpenCV, NumPy, mediapipe, PyQt6) are
  installed from their standard PyPI wheels, which target a generic x86-64 baseline, not an
  AVX2/AVX-512-only build. This should mean it isn't limited to modern CPUs only — but I
  have no way to verify this on a second machine from here.
* **Windows version floor:** Python 3.12 itself requires Windows 8.1 or newer, so realistically
  this targets Windows 10/11 x64, which is what you're building for anyway.
* **What I cannot guarantee, because I have no second Windows machine to test on:** that it
  actually launches cleanly on hardware other than yours. The honest way to find out is to
  run the installer on a second, different PC (ideally your friend's) before calling this
  done — specifically watch for an "illegal instruction" crash on launch (CPU mismatch, see
  above), a Visual C++ runtime error (shouldn't happen given the point above, but worth
  ruling out), or a "Windows protected your PC" SmartScreen prompt (expected and harmless —
  click "More info" -> "Run anyway").
* **Running from source instead of compiling** (`./jarvis.sh run`) does not meaningfully widen
  compatibility beyond the above — it uses the exact same prebuilt wheels for OpenCV/NumPy/etc.,
  so the same CPU-baseline reasoning applies either way. Source vs. compiled is not a
  compatibility lever here; it only changes the "cannot see the code" question discussed
  earlier in this build.

## Limits
* Core is Python; only the build/launch layer is bash.
* Built on Linux: the native compile, DPAPI, installer and fallback-engine scripts were **not run**. Run `./jarvis.sh test` first, then build, then actually launch the installed app before relying on it.
* Nuitka compiles to native code, which is a real barrier (no source or bytecode shipped) but is not literal obfuscation — a determined person with a disassembler can still study machine code, same as for any compiled program. The `--engine=pyinstaller` fallback is a bytecode bundle and is easier to pull apart than the native build; use it only if the native build fails on your machine.
* PyQt6 + mediapipe + OpenCV + Playwright is a lot to compile natively; the first `./jarvis.sh build` can take well over an hour.
* The Android companion was renamed too (package `com.jarvis`, mDNS `_JARVIS`): rebuild and reinstall it; an old installed Brahma phone app will not pair.
* The bundled Spotify Node server reads its own config file and can't see the vault copy.
* Self-heal cannot patch a compiled app; it saves proposals in `%LOCALAPPDATA%\JarvisAI\patch_proposals`.
* LICENSE (source-available, personal use, **no distribution**) and TRADEMARK/CONTRIBUTING files were left untouched on purpose. Giving this build to a friend is not permitted by it.
