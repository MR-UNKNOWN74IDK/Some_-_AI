"""
core/safety_stack.py — every safety mechanism from both projects, stacked.

Layers (outermost first).  A request has to get through all of them:

  L0  HARD BLOCKS        always on, cannot be switched off.  Disk wipes,
                         remote-code one-liners, credential-vault access,
                         writes to protected paths, persistence tricks.
  L1  CODE SCAN          AST analysis of any code Jarvis wrote or patched
                         (forged skills, self-heal patches).  Superset of the
                         old Skill Crucible string check, which only looked at
                         string literals and was trivially bypassed.
  L2  TOOL GATE          risk tiers for the model's tool calls, enforced at
                         the single dispatch point in main.py.  Uses the
                         unforgeable HUD confirmation from core/confirm.py.
  L3  SANDBOX ENV        forged-skill test runs get a scrubbed environment
                         (no keys/tokens, throw-away AppData, so the vault
                         is not where the code would expect it).
  L4  INTEGRITY          SHA-256 of every forged skill is kept in the
                         encrypted vault; a skill edited on disk afterwards
                         is quarantined instead of loaded.
  L5  AUTONOMY BUDGET    Ultron mode may self-heal / forge at most N times
                         per hour, so a bad loop cannot run away.
  L6  UNDO + AUDIT       reversible actions go on core/undo.py; every
                         decision lands in logs/safety_audit.jsonl.

Honest limits: this is defence in depth, not a VM.  Static analysis cannot
catch every obfuscation and the skill test still runs as the same Windows
user.  That is why Jarvis mode (the default) asks before registering any new
skill, and why lockdown exists.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core import modes
from core.user_paths import get_user_data_dir

# ═════════════════════════════ settings helpers ════════════════════════════

def _get_setting(key: str, default: Any) -> Any:
    try:
        from memory import config_manager
        return config_manager.get_setting(key, default)
    except Exception:
        return default


def layer_enabled(name: str) -> bool:
    """Layers L1-L5 can be toggled in the Control Center.  L0 cannot."""
    return bool(_get_setting(f"safety_layer_{name}", True))


# ═════════════════════════════ audit log (L6) ══════════════════════════════

_audit_lock = threading.Lock()
_SECRET_RE = re.compile(
    r"(AIza[0-9A-Za-z_\-]{20,}|sk-[A-Za-z0-9_\-]{16,}|xox[bp]-[A-Za-z0-9\-]{10,}"
    r"|gh[pous]_[A-Za-z0-9]{20,}|[A-Za-z0-9_\-]{24}\.[A-Za-z0-9_\-]{6}\.[A-Za-z0-9_\-]{20,})"
)


def _redact(text: str, limit: int = 300) -> str:
    text = _SECRET_RE.sub("[redacted]", str(text))
    return text if len(text) <= limit else text[:limit] + "…"


def _audit_path() -> Path:
    d = get_user_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "safety_audit.jsonl"


def audit(event: str, *, layer: str = "", tool: str = "", verdict: str = "",
          detail: str = "", **extra: Any) -> None:
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, "layer": layer,
           "mode": modes.effective_mode(), "tool": tool, "verdict": verdict,
           "detail": _redact(detail)}
    for k, v in extra.items():
        rec[k] = _redact(v) if isinstance(v, str) else v
    try:
        with _audit_lock:
            p = _audit_path()
            if p.exists() and p.stat().st_size > 2_000_000:
                p.replace(p.with_suffix(".1.jsonl"))
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_audit(limit: int = 200) -> List[Dict[str, Any]]:
    try:
        lines = _audit_path().read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(x) for x in lines if x.strip()]
    except Exception:
        return []


# ═════════════════════════════ L0: hard blocks ═════════════════════════════

_FLAGS = re.IGNORECASE
HARD_BLOCK_PATTERNS: List[Tuple[re.Pattern, str]] = [(re.compile(p, _FLAGS), why) for p, why in [
    (r"\bformat\s+[a-z]:", "formatting a drive"),
    (r"\bformat-volume\b|\bclear-disk\b|\bremove-partition\b|\bdiskpart\b", "disk/partition destruction"),
    (r"\bvssadmin\b[^\n]*\bdelete\b|\bwmic\b[^\n]*shadowcopy[^\n]*delete", "deleting shadow copies"),
    (r"\bbcdedit\b", "editing the boot configuration"),
    (r"\bcipher\s+/w", "wiping free disk space"),
    (r"\bwevtutil\s+(cl|clear-log)\b|\bclear-eventlog\b", "clearing event logs"),
    (r"(remove-item|\brm\b|\bdel\b|\brd\b|\brmdir\b)[^\n;|&]*"
     r"(-recurse|\s/s\b|\s-r\b|\s-rf\b)[^\n;|&]*\s[\"']?[a-z]:[\\/]*[\"']?\s*(\*|$|[;|&])",
     "recursive delete of a drive root"),
    (r"(remove-item|\brm\b|\bdel\b|\brd\b|\brmdir\b)[^\n;|&]*\\windows\\(system32|syswow64)",
     "deleting Windows system files"),
    (r"\breg(\.exe)?\s+(delete|add)\s+[\"']?hk(lm|ey_local_machine)", "editing machine-wide registry"),
    (r"\\currentversion\\run(once)?\b", "registry autorun persistence"),
    (r"set-mppreference[^\n]*-disable|\bsc(\.exe)?\s+(stop|delete|config)\s+windefend",
     "disabling antivirus"),
    (r"\bnet(1)?\s+user\b[^\n]*/add|\bnet(1)?\s+localgroup\s+administrators", "creating accounts / admin rights"),
    (r"(iex|invoke-expression)[^\n]*(downloadstring|invoke-webrequest|\biwr\b|irm\b|invoke-restmethod)"
     r"|(downloadstring|invoke-webrequest|\biwr\b|\birm\b)[^\n]*\|\s*(iex|invoke-expression)",
     "download-and-execute one-liner"),
    (r"-enc(odedcommand)?\s+[a-z0-9+/=]{20,}", "encoded PowerShell command"),
    (r"(curl|wget)[^\n]*\|\s*(ba)?sh\b", "pipe-to-shell"),
    (r"start menu\\programs\\startup|\\appdata\\roaming\\microsoft\\windows\\start menu", "startup-folder persistence"),
    (r"\bschtasks(\.exe)?\b[^\n]*/create", "creating scheduled tasks"),
]]

# Paths nothing the model writes may touch.  (lower-cased, backslash-normalised)
PROTECTED_PATH_FRAGMENTS = (
    "\\windows\\system32", "\\windows\\syswow64", "\\windows\\boot",
    "\\programdata\\microsoft\\windows\\start menu",
    "\\start menu\\programs\\startup",
    "\\jarvisai\\vault", "secrets.bin", "api_keys.json", "email_credentials.json",
    "\\.ssh\\", "ntuser.dat",
)

_PATH_ARG_KEYS = ("file_path", "path", "destination", "dest", "target", "output", "output_path",
                  "save_path", "directory", "folder", "new_path")
_WRITEISH_TOOLS = {"file_write", "file_edit", "file_controller", "smart_organizer",
                   "desktop_control", "word_document", "pdf_document", "presentation_builder",
                   "spreadsheet_builder"}


def _norm_path(p: str) -> str:
    return str(p).replace("/", "\\").lower()


def _iter_strings(obj: Any, depth: int = 0) -> Iterable[str]:
    if depth > 6:
        return
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v, depth + 1)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            yield from _iter_strings(v, depth + 1)


def scan_text_for_hard_blocks(text: str) -> Optional[str]:
    for rx, why in HARD_BLOCK_PATTERNS:
        if rx.search(text):
            return why
    return None


def protected_path_hit(path: str) -> Optional[str]:
    n = _norm_path(path)
    for frag in PROTECTED_PATH_FRAGMENTS:
        if frag in n:
            return frag
    return None


# ═════════════════════════════ L2: tool gate ═══════════════════════════════

SAFE, RISKY, CRITICAL, BLOCK = "safe", "risky", "critical", "block"

# Always need a human, in every mode: they reach other people, other devices,
# or add new capabilities.
_CRITICAL_TOOLS = {
    "send_message", "instagram_post_photo", "instagram_post_reel", "instagram_send_dm",
    "instagram_reply", "upload_video", "unlock_device", "connect_pair_device", "skill_install",
}
# Need a human in Jarvis; run on their own (but audited) in Ultron.
_RISKY_TOOLS = {
    "bash", "python_repl", "file_write", "file_edit", "git_manager", "dev_agent", "agent_task",
    "computer_control", "desktop_control", "smart_organizer", "file_controller", "game_updater",
    "connect_execute", "skill_forge", "dynamic_skill", "skill_execute", "reverse_engineer",
    "auto_heal", "test_and_heal", "subagent_task", "browser_control", "google_workspace",
    "manage_local_model",
}
# Verbs that promote a RISKY tool to CRITICAL.
_DESTRUCTIVE_VERBS = ("delete", "remove", "erase", "wipe", "format", "uninstall", "kill",
                      "shutdown", "restart", "send", "post", "empty_trash", "purge", "overwrite")


@dataclass
class Verdict:
    action: str                       # "allow" | "confirm" | "block"
    level: str = SAFE
    reason: str = ""
    layer: str = ""
    title: str = ""
    detail: str = ""

    @property
    def allowed(self) -> bool:
        return self.action == "allow"


def _summarise_args(args: Dict[str, Any], limit: int = 220) -> str:
    try:
        text = json.dumps(args, ensure_ascii=False, default=str)
    except Exception:
        text = str(args)
    return _redact(text, limit)


def classify_tool(name: str, args: Dict[str, Any]) -> str:
    n = (name or "").lower()
    if n in _CRITICAL_TOOLS:
        return CRITICAL
    if n in _RISKY_TOOLS:
        verb_fields = " ".join(str(args.get(k, "")) for k in ("action", "operation", "mode", "command_type")).lower()
        if any(v in verb_fields for v in _DESTRUCTIVE_VERBS):
            return CRITICAL
        return RISKY
    return SAFE


def trusted_tools() -> set:
    raw = _get_setting("safety_trusted_tools", [])
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.split(",")]
    return {str(x).lower() for x in raw if str(x).strip()}


def check_tool(name: str, args: Dict[str, Any], *, approved: bool = False) -> Verdict:
    """The decision for one tool call.  `approved=True` means the human already
    pressed CONFIRM on the HUD — it skips L2 prompts but never L0 blocks."""
    args = args or {}

    # ── L0 (always on) ────────────────────────────────────────────────────
    for s in _iter_strings({k: v for k, v in args.items() if not str(k).startswith("__")}):
        why = scan_text_for_hard_blocks(s)
        if why:
            audit("tool_blocked", layer="L0", tool=name, verdict="block", detail=why,
                  args=_summarise_args(args))
            return Verdict("block", BLOCK, f"Blocked by safety stack: {why}.", "L0")
    if name.lower() in _WRITEISH_TOOLS:
        for k in _PATH_ARG_KEYS:
            v = args.get(k)
            if isinstance(v, str):
                hit = protected_path_hit(v)
                if hit:
                    audit("tool_blocked", layer="L0", tool=name, verdict="block",
                          detail=f"protected path {hit}", args=_summarise_args(args))
                    return Verdict("block", BLOCK, f"Blocked: '{v}' is a protected location.", "L0")

    # ── L2 ────────────────────────────────────────────────────────────────
    if not layer_enabled("tool_gate") or approved:
        return Verdict("allow", SAFE, "gate disabled or already approved", "L2")

    level = classify_tool(name, args)
    pol = modes.policy()
    if level == SAFE:
        return Verdict("allow", SAFE, "", "L2")
    if name.lower() in trusted_tools() and level == RISKY:
        audit("tool_allowed", layer="L2", tool=name, verdict="trusted", args=_summarise_args(args))
        return Verdict("allow", level, "trusted tool", "L2")
    if level == RISKY and pol.auto_run_risky_tools:
        audit("tool_allowed", layer="L2", tool=name, verdict="auto-ultron", args=_summarise_args(args))
        return Verdict("allow", level, "Ultron mode: risky tool runs autonomously", "L2")

    title = f"Allow Jarvis to run '{name}'?" if level == RISKY else f"Confirm: {name}"
    detail = _summarise_args(args)
    audit("tool_confirm_requested", layer="L2", tool=name, verdict=level, args=detail)
    return Verdict("confirm", level, f"{level} tool needs approval", "L2", title, detail)


# ═════════════════════════════ L1: code scan ═══════════════════════════════

@dataclass
class CodeReport:
    blocked: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blocked

    def summary(self) -> str:
        parts = [f"BLOCK: {x}" for x in self.blocked] + [f"warn: {x}" for x in self.warnings]
        return "; ".join(parts[:8]) or "clean"


# Calls that are refused outright in generated code.
_BLOCK_CALLS = {
    "eval": "eval() on dynamic input", "exec": "exec() of dynamic code",
    "__import__": "dynamic __import__", "os.system": "os.system shell call (use subprocess without shell)",
    "os.startfile": "launching arbitrary files", "ctypes.windll": "direct Win32 calls",
    "winreg.setvalue": "registry write", "winreg.setvalueex": "registry write",
    "winreg.createkey": "registry write", "winreg.createkeyex": "registry write",
    "winreg.deletekey": "registry delete", "winreg.deletevalue": "registry delete",
    "pickle.loads": "unpickling (code execution)", "pickle.load": "unpickling (code execution)",
    "marshal.loads": "marshal.loads (code execution)", "builtins.exec": "exec", "builtins.eval": "eval",
}
_BLOCK_IMPORTS = {
    "secrets_store": "credential vault access", "core.secrets_store": "credential vault access",
    "keyring": "OS credential access", "win32crypt": "DPAPI credential access",
    "browser_cookie3": "browser cookie theft", "pynput": "keylogging",
}
_WARN_CALLS = {
    "shutil.rmtree": "recursive delete", "os.remove": "file delete", "os.unlink": "file delete",
    "os.rmdir": "directory delete", "os.removedirs": "directory delete", "pathlib.path.unlink": "file delete",
    "os.popen": "shell pipe", "socket.socket": "raw sockets", "subprocess.popen": "spawns processes",
    "subprocess.run": "spawns processes", "subprocess.call": "spawns processes",
    "subprocess.check_output": "spawns processes", "subprocess.check_call": "spawns processes",
    "importlib.import_module": "dynamic import", "getattr": "dynamic attribute (possible obfuscation)",
    "ctypes.cdll": "native library load", "ctypes.cdll.loadlibrary": "native library load",
    "keyboard.hook": "global keyboard hook", "keyboard.on_press": "global keyboard hook",
}
_SENSITIVE_STRINGS = {
    "api_keys.json": "credential file", "secrets.bin": "credential vault",
    "email_credentials.json": "credential file", "discord_bot.json": "credential file",
    "spotify-config.json": "credential file", "\\vault": "credential vault",
    "boot_sentry": "self-protection module", "auto_heal_engine": "self-protection module",
    "safety_stack": "safety layer", "secrets_store": "credential vault",
    "install_wizard": "installer", "build_exe": "build tooling",
}


def _dotted(node: ast.AST) -> str:
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif isinstance(node, ast.Call):  # e.g. Path(...).unlink
        inner = _dotted(node.func)
        if inner:
            parts.append(inner)
    return ".".join(reversed(parts)).lower()


def analyze_code(source: str, *, origin: str = "skill") -> CodeReport:
    """AST-level inspection.  `origin` is only used for the audit trail."""
    rep = CodeReport()
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        rep.blocked.append(f"syntax error: {e.msg} (line {e.lineno})")
        return rep

    for node in ast.walk(tree):
        # imports ------------------------------------------------------------
        if isinstance(node, ast.Import):
            for a in node.names:
                why = _BLOCK_IMPORTS.get(a.name.lower()) or _BLOCK_IMPORTS.get(a.name.split(".")[-1].lower())
                if why:
                    rep.blocked.append(f"import {a.name}: {why}")
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").lower()
            why = _BLOCK_IMPORTS.get(mod) or _BLOCK_IMPORTS.get(mod.split(".")[-1])
            if not why:
                for a in node.names:
                    if a.name.lower() in _BLOCK_IMPORTS:
                        why = _BLOCK_IMPORTS[a.name.lower()]
            if why:
                rep.blocked.append(f"from {node.module} import …: {why}")

        # calls --------------------------------------------------------------
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            bare = name.split(".")[-1] if name else ""
            hit = _BLOCK_CALLS.get(name) or (_BLOCK_CALLS.get(bare) if name in ("eval", "exec", "__import__") else None)
            if not hit and name.startswith("ctypes.windll"):
                hit = _BLOCK_CALLS["ctypes.windll"]
            if hit:
                rep.blocked.append(f"{name}(): {hit}")
                continue
            whit = _WARN_CALLS.get(name)
            if name == "getattr" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                whit = None  # getattr(x, "literal") is ordinary
            if whit:
                rep.warnings.append(f"{name}(): {whit}")
            # subprocess with shell=True: refuse if the command trips L0, else warn
            if name.startswith("subprocess.") or name == "os.popen":
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        rep.warnings.append("subprocess shell=True")
            # open(..., 'w') to a protected path
            if name in ("open", "io.open", "pathlib.path.write_text", "pathlib.path.write_bytes"):
                for a in node.args[:1]:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str) and protected_path_hit(a.value):
                        rep.blocked.append(f"writes protected path {a.value!r}")

        # string constants ------------------------------------------------------
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value
            if len(s) < 4:
                continue
            why = scan_text_for_hard_blocks(s)
            if why:
                rep.blocked.append(f"string literal: {why}")
            low = s.lower()
            for frag, label in _SENSITIVE_STRINGS.items():
                if frag in low:
                    rep.blocked.append(f"references {frag!r} ({label})")
                    break
            if protected_path_hit(s):
                rep.blocked.append(f"references protected path {s[:60]!r}")

    # de-duplicate, keep order
    rep.blocked = list(dict.fromkeys(rep.blocked))
    rep.warnings = list(dict.fromkeys(rep.warnings))
    if rep.blocked:
        audit("code_blocked", layer="L1", detail=rep.summary(), origin=origin)
    return rep


def analyze_fragment(snippet: str, *, origin: str = "patch") -> CodeReport:
    """Scan a code *fragment* (e.g. the replacement chunk of a self-heal patch),
    which usually is not valid Python on its own (dangling indentation, an
    `else:` branch...).  Tries dedent, then wrapping in a function; if it still
    does not parse, falls back to the pattern-level checks only."""
    import textwrap
    text = textwrap.dedent(snippet)
    for candidate in (text, "def _fragment():\n" + textwrap.indent(text, "    ")):
        try:
            ast.parse(candidate)
            return analyze_code(candidate, origin=origin)
        except SyntaxError:
            continue
    rep = CodeReport()
    why = scan_text_for_hard_blocks(snippet)
    if why:
        rep.blocked.append(f"fragment: {why}")
    low = snippet.lower()
    for frag, label in _SENSITIVE_STRINGS.items():
        if frag in low:
            rep.blocked.append(f"references {frag!r} ({label})")
    for bad in ("os.system(", "eval(", "exec(", "__import__(", "ctypes.windll", "pickle.load"):
        if bad in snippet:
            rep.blocked.append(f"fragment uses {bad}")
    rep.warnings.append("fragment could not be parsed; pattern scan only")
    if rep.blocked:
        audit("code_blocked", layer="L1", detail=rep.summary(), origin=origin)
    return rep


def check_code(source: str, *, origin: str = "skill") -> CodeReport:
    """L1 entry point; honours the Control Center toggle for *warnings only* —
    BLOCK findings are enforced even if L1 is switched off, because they are
    L0-class (credential access, wipe commands)."""
    rep = analyze_code(source, origin=origin)
    if not layer_enabled("code_scan"):
        rep.warnings.clear()
    return rep


# ═════════════════════════════ skill registration decision ═════════════════

def skill_registration_decision(report: CodeReport) -> str:
    """'deny' | 'confirm' | 'auto'."""
    if report.blocked:
        return "deny"
    if not autonomy_allowed("auto_register_skills", consume=False)[0]:
        return "confirm"
    return "confirm" if report.warnings else "auto"


# ═════════════════════════════ L3: sandbox env ═════════════════════════════

_SECRETISH_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|SESSION|COOKIE)", re.I)


def sandbox_env() -> Tuple[Dict[str, str], str]:
    """Environment for running untrusted skill code.  Returns (env, tmpdir)."""
    tmp = tempfile.mkdtemp(prefix="jarvis_sandbox_")
    if not layer_enabled("sandbox_env"):
        return dict(os.environ), tmp
    env = {k: v for k, v in os.environ.items() if not _SECRETISH_ENV.search(k)}
    for var in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "TMPDIR"):
        env[var] = tmp
    env["JARVIS_SANDBOX"] = "1"
    return env, tmp


# ═════════════════════════════ L4: integrity ═══════════════════════════════

_HASH_STORE = "skill_hashes"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_skill_hash(path: Path) -> None:
    try:
        from core import secrets_store
        data = secrets_store.get_all(_HASH_STORE)
        data[str(Path(path).name)] = _sha256(Path(path))
        secrets_store.set_all(data, _HASH_STORE)
    except Exception as exc:
        audit("integrity_record_failed", layer="L4", detail=str(exc))


def verify_skill(path: Path) -> bool:
    """True if the file matches the hash recorded at forge time.  Files that
    were never recorded (shipped with the app) are not this layer's concern."""
    if not layer_enabled("integrity"):
        return True
    try:
        from core import secrets_store
        expected = secrets_store.get_all(_HASH_STORE).get(Path(path).name)
        if expected is None:
            return True
        ok = expected == _sha256(Path(path))
        if not ok:
            audit("skill_quarantined", layer="L4", verdict="block",
                  detail=f"{Path(path).name} changed on disk since it was forged")
        return ok
    except Exception:
        return True


# ═════════════════════════════ L5: autonomy budget ═════════════════════════

_budget_lock = threading.Lock()
_budget_events: List[float] = []


def autonomy_allowed(kind: str, *, consume: bool = True) -> Tuple[bool, str]:
    """kind: 'auto_self_heal' | 'auto_register_skills' | 'background_sentries'."""
    if modes.lockdown_active():
        return False, "lockdown is active"
    pol = modes.policy()
    if not getattr(pol, kind, False):
        return False, f"{pol.mode} mode does not allow {kind.replace('_', ' ')}"
    if kind in ("auto_self_heal", "auto_register_skills") and layer_enabled("autonomy_budget"):
        now = time.time()
        with _budget_lock:
            _budget_events[:] = [t for t in _budget_events if now - t < 3600]
            if len(_budget_events) >= pol.autonomy_budget_per_hour:
                audit("autonomy_budget_exhausted", layer="L5", detail=kind)
                return False, "hourly autonomy budget used up"
            if consume:
                _budget_events.append(now)
    return True, "ok"


def reset_budget_for_tests() -> None:
    with _budget_lock:
        _budget_events.clear()
