"""
core/modes.py — the two operating modes.

JARVIS  (default)  Conversation and information only. Cannot execute anything.
ULTRON             Execution only (apps, files, commands, devices, messages,
                   self-heal, skill forging). Does not make conversation.

Asking a mode for the other kind of work never runs silently: see
core/mode_router.py (it notes the request and offers to switch).
Ultron still passes through the safety stack (core/safety_stack.py): hard
blocks, and critical actions such as messaging people or deleting files still
need a HUD confirmation.  `safety_lockdown` forces JARVIS (so nothing can be
executed) and disables every autonomous feature.

The mode is stored in app_settings.json ("operating_mode").
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, List

JARVIS = "jarvis"
ULTRON = "ultron"
VALID = (JARVIS, ULTRON)

_listeners: List[Callable[[str], None]] = []
_lock = threading.Lock()


@dataclass(frozen=True)
class Policy:
    mode: str
    auto_self_heal: bool          # patch own code after a crash without asking
    auto_register_skills: bool    # forged skills go live without approval
    auto_run_risky_tools: bool    # RISKY-tier tools run without a HUD prompt
    background_sentries: bool     # crash monitor, net sentinel, proactive engine
    autonomy_budget_per_hour: int # cap on heals + forges (runaway-loop guard)


_POLICIES = {
    JARVIS: Policy(JARVIS, False, False, False, False, 0),
    ULTRON: Policy(ULTRON, True, True, True, True, 12),
}


def _settings():
    from memory import config_manager
    return config_manager


def get_mode() -> str:
    try:
        m = str(_settings().get_setting("operating_mode", JARVIS)).lower()
    except Exception:
        m = JARVIS
    return m if m in VALID else JARVIS


def lockdown_active() -> bool:
    try:
        return bool(_settings().get_setting("safety_lockdown", False))
    except Exception:
        return False


def effective_mode() -> str:
    """The mode actually in force (lockdown always wins)."""
    return JARVIS if lockdown_active() else get_mode()


def policy() -> Policy:
    return _POLICIES[effective_mode()]


def is_ultron() -> bool:
    return effective_mode() == ULTRON


def set_mode(mode: str) -> str:
    mode = (mode or "").lower().strip()
    if mode not in VALID:
        raise ValueError(f"mode must be one of {VALID}")
    _settings().set_setting("operating_mode", mode)
    try:
        from core import safety_stack
        safety_stack.audit("mode_change", layer="modes", detail=f"-> {mode}")
    except Exception:
        pass
    with _lock:
        cbs = list(_listeners)
    for cb in cbs:
        try:
            cb(effective_mode())
        except Exception:
            pass
    return mode


def on_change(cb: Callable[[str], None]) -> None:
    with _lock:
        _listeners.append(cb)


def banner() -> str:
    if lockdown_active():
        return "LOCKDOWN — autonomous features disabled"
    return {"jarvis": "JARVIS — conversation only (cannot execute)",
            "ultron": "ULTRON — execution only (safety stack active)"}[get_mode()]
