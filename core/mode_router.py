"""
core/mode_router.py — Jarvis talks, Ultron acts.

JARVIS  conversation + information only. It cannot execute anything.
ULTRON  execution only. It does not make conversation.

If you ask a mode for the other mode's kind of work, it does not do it and does
not silently switch: it remembers your request, tells you, and waits.

    [Jarvis] "please open Spotify"
        -> "I'm in Jarvis mode and can't execute things. Say 'Ultron, please open
            Spotify' or just say yes and I'll switch to Ultron and run it."
    [Jarvis] "switch to Ultron"   (or "yes")
        -> switches to Ultron and runs "please open Spotify" immediately.
    [Ultron] "what's the weather?"
        -> offers to hand over to Jarvis, same flow in reverse.

You can also switch any time with nothing pending ("switch to Jarvis",
"Ultron mode"), or address a mode by name ("Ultron, open Spotify").
"Aldron"/"Altron" (speech-recognition spellings of Ultron) are accepted.

Two enforcement points:
  * route_text()  — typed / mobile / dashboard commands, decided here before any
                    model is called (deterministic).
  * gate_tool()   — every tool call from the voice model, in main._execute_tool.
                    This is the hard guarantee that Jarvis cannot execute.
Keeping Ultron from chatting during *voice* turns relies on the mode prompt plus
the tool gate (an info tool in Ultron is refused and offered to Jarvis); it
cannot be enforced as strictly as a tool call.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Optional

from core import modes

PENDING_TTL = 180  # seconds

_ALIASES = {"jarvis": modes.JARVIS, "ultron": modes.ULTRON, "aldron": modes.ULTRON,
            "altron": modes.ULTRON, "oltron": modes.ULTRON, "ultra": modes.ULTRON}
_NAME_RX = "|".join(_ALIASES)
_DISPLAY = {modes.JARVIS: "Jarvis", modes.ULTRON: "Ultron"}

# ── tool classes ─────────────────────────────────────────────────────────────
# Information/chat tools: allowed in Jarvis, refused in Ultron.
JARVIS_TOOLS = {
    "set_operating_mode", "recall_memory", "save_memory", "get_sensorium_telemetry", "web_search",
    "weather_report", "screen_process", "flight_finder", "daily_briefing", "system_diagnostics",
    "mcp_status", "skill_list", "todo_read", "connect_list_devices", "connect_get_device",
    "connect_get_capabilities", "check_instagram_messages", "instagram_get_user_info",
    "file_read", "glob", "grep",
}
# Always allowed in both modes (the switch itself).
NEUTRAL_TOOLS = {"set_operating_mode"}
# Everything else (open_app, bash, send_message, file_write, skills, MCP...) is Ultron-only.

# ── text classification ──────────────────────────────────────────────────────
_ACTION_VERBS = (
    "open|launch|start|run|execute|close|quit|exit|kill|play|pause|resume|stop|skip|next|previous|"
    "volume|mute|unmute|send|text|message|call|dial|post|upload|create|make|build|write|edit|delete|"
    "remove|rename|move|copy|paste|install|uninstall|download|save|set|schedule|remind|turn|toggle|"
    "shutdown|shut|restart|reboot|lock|unlock|screenshot|type|click|scroll|press|organize|clean|fix|"
    "heal|forge|book|order|buy|commit|push|deploy|take|connect|disconnect|enable|disable|increase|"
    "decrease|raise|lower|brighten|dim|switch off|switch on|generate|record|capture|print|zip|unzip|"
    "extract|convert|compile|execute|git|search my|find my|organise"
)
_ACT_START = re.compile(rf"^(?:{_ACTION_VERBS})\b", re.I)
_ACT_ANY = re.compile(rf"\b(?:{_ACTION_VERBS})\b", re.I)
_Q_START = re.compile(r"^(what|whats|what's|who|why|how|when|where|which|is|are|was|were|do|does|did|"
                      r"tell me|explain|define|describe|give me|show me|summari[sz]e|compare|should|"
                      r"will|would|could you tell|any|got any)\b", re.I)
_POLITE = re.compile(r"^(?:(?:hey|hi|ok|okay|please|kindly|just|now|also|and|then|so)\s+)+", re.I)
_CAN_YOU = re.compile(r"^(?:can|could|would|will)\s+you\s+(?:please\s+)?", re.I)

_SWITCH_RXES = [
    re.compile(rf"^(?:please\s+)?(?:(?:hey\s+)?(?:{_NAME_RX})[,:\s]+)?(?:switch|change|go|shift|move|swap|hand(?:\s+over)?)"
               rf"(?:\s+(?:over|back))?(?:\s+to)?\s+(?:the\s+)?({_NAME_RX})(?:\s+mode)?\b[\s.!]*(?:please)?[\s.!]*$", re.I),
    re.compile(rf"^(?:please\s+)?(?:activate|enable|enter|engage|start|use)\s+({_NAME_RX})(?:\s+mode)?[\s.!]*$", re.I),
    re.compile(rf"^({_NAME_RX})\s+mode(?:\s+(?:on|please|now))?[\s.!]*$", re.I),
    re.compile(rf"^(?:back\s+to|return\s+to)\s+({_NAME_RX})(?:\s+mode)?[\s.!]*$", re.I),
]
_ADDRESS = re.compile(rf"^(?:(?:hey|ok|okay)\s+)?({_NAME_RX})\b[\s,:\-]*(.*)$", re.I | re.S)
_YES = re.compile(r"^(?:yes|yeah|yep|yup|sure|ok|okay|go ahead|do it|switch|switch it|confirm|"
                  r"please do|proceed|affirmative|yes please|yes switch|go for it)\b[\s.!,]*(?:please)?[\s.!]*$", re.I)
_NO = re.compile(r"^(?:no|nope|nah|cancel|never ?mind|stay|don'?t|stop|forget it)\b[\s.!,]*$", re.I)


# Words that answer an on-screen prompt or acknowledge something; never worth a mode offer.
_PASSTHROUGH = re.compile(r"^(?:thanks|thank you|thx|ok|okay|cool|great|nice|good|got it|fine|hello|hi|hey|"
                          r"stop|cancel|abort|halt|confirm|deny|approve|reject|allow)\b[\s.!,]*$", re.I)


@dataclass
class Decision:
    text: str = ""              # what to process next (empty if nothing)
    reply: str = ""             # what to say / show to the user
    switched_to: Optional[str] = None
    stop: bool = False          # True = do not send `text` to the model


@dataclass
class _Pending:
    text: str
    target: str
    at: float


_lock = threading.Lock()
_pending: Optional[_Pending] = None
_last_user_utterance = ""


# ── pending request ──────────────────────────────────────────────────────────

def set_pending(text: str, target: str) -> None:
    global _pending
    with _lock:
        _pending = _Pending(text.strip(), target, time.time())


def get_pending() -> Optional[_Pending]:
    with _lock:
        if _pending and time.time() - _pending.at > PENDING_TTL:
            return None
        return _pending


def clear_pending() -> None:
    global _pending
    with _lock:
        _pending = None


def note_user_utterance(text: str) -> None:
    """Voice path: remember what the user last said so a blocked tool call can
    be replayed after a mode switch."""
    global _last_user_utterance
    _last_user_utterance = (text or "").strip()


def last_user_utterance() -> str:
    return _last_user_utterance


# ── classification ───────────────────────────────────────────────────────────

def _strip_polite(text: str) -> str:
    t = text.strip()
    for _ in range(3):
        t2 = _CAN_YOU.sub("", _POLITE.sub("", t)).strip()
        if t2 == t:
            break
        t = t2
    return t


def classify(text: str) -> str:
    """'action' (needs Ultron) or 'chat' (Jarvis)."""
    t = _strip_polite(text)
    if _ACT_START.match(t):
        return "action"
    if t.endswith("?") or _Q_START.match(t):
        return "chat"
    return "action" if _ACT_ANY.search(t) else "chat"


def needed_mode(text: str) -> str:
    return modes.ULTRON if classify(text) == "action" else modes.JARVIS


def parse_switch(text: str) -> Optional[str]:
    t = text.strip()
    for rx in _SWITCH_RXES:
        m = rx.match(t)
        if m:
            return _ALIASES[m.group(1).lower()]
    return None


# ── switching ────────────────────────────────────────────────────────────────

def _blocked_by_lockdown(target: str) -> bool:
    return target == modes.ULTRON and modes.lockdown_active()


def _apply_switch(target: str) -> str:
    modes.set_mode(target)
    return target


def _offer(text: str, cur: str) -> Decision:
    need = modes.ULTRON if cur == modes.JARVIS else modes.JARVIS
    if _blocked_by_lockdown(need):
        return Decision(reply="Lockdown is on, so I can't execute anything. Turn lockdown off in the Control Center first.",
                        stop=True)
    set_pending(text, need)
    n = _DISPLAY[need]
    if cur == modes.JARVIS:
        reply = (f"I'm in Jarvis mode, so I can only talk, not execute. Say \"Ultron, {text}\" — "
                 f"or just say yes and I'll switch to Ultron and run it now.")
    else:
        reply = (f"I'm in Ultron mode, so I only execute, I don't chat. Say \"Jarvis, {text}\" — "
                 f"or just say yes and I'll switch to Jarvis and answer it.")
    return Decision(reply=reply, stop=True)


def route_text(text: str) -> Decision:
    """Deterministic routing for typed / mobile / dashboard commands."""
    raw = (text or "").strip()
    if not raw:
        return Decision(stop=True)
    cur = modes.effective_mode()
    pend = get_pending()

    # 1. explicit switch command
    target = parse_switch(raw)
    if target:
        if _blocked_by_lockdown(target):
            return Decision(reply="Lockdown is on, so Ultron is unavailable.", stop=True)
        _apply_switch(target)
        n = _DISPLAY[target]
        if pend and pend.target == target:
            clear_pending()
            return Decision(text=pend.text, reply=f"{n} mode. Carrying out: {pend.text}", switched_to=target)
        clear_pending()
        return Decision(reply=f"{n} mode.", switched_to=target, stop=True)

    # 2. confirmation / refusal of a pending offer
    if pend:
        if _YES.match(raw):
            if _blocked_by_lockdown(pend.target):
                return Decision(reply="Lockdown is on, so Ultron is unavailable.", stop=True)
            _apply_switch(pend.target)
            clear_pending()
            return Decision(text=pend.text, reply=f"{_DISPLAY[pend.target]} mode. Carrying out: {pend.text}",
                            switched_to=pend.target)
        if _NO.match(raw):
            clear_pending()
            return Decision(reply=f"Okay, staying in {_DISPLAY[cur]} mode.", stop=True)

    # 3. addressed by name ("Ultron, open Spotify")
    text_for_class = raw
    m = _ADDRESS.match(raw)
    if m:
        addressed, rest = _ALIASES[m.group(1).lower()], m.group(2).strip()
        if not rest:
            if addressed != cur and not _blocked_by_lockdown(addressed):
                _apply_switch(addressed)
                clear_pending()
                return Decision(reply=f"{_DISPLAY[addressed]} here.", switched_to=addressed, stop=True)
            return Decision(reply=f"{_DISPLAY[cur]} here. Go ahead.", stop=True)
        if addressed != cur:
            if _blocked_by_lockdown(addressed):
                return Decision(reply="Lockdown is on, so Ultron is unavailable.", stop=True)
            _apply_switch(addressed)
            cur = addressed
            clear_pending()
            sw = addressed
        else:
            sw = None
        text_for_class = rest
        need = needed_mode(rest)
        if need == cur:
            return Decision(text=rest, switched_to=sw,
                            reply=f"{_DISPLAY[cur]} here." if sw else "")
        d = _offer(rest, cur)
        d.switched_to = sw
        return d

    # 4. plain input: does it belong to this mode?
    if _YES.match(raw) or _NO.match(raw) or _PASSTHROUGH.match(raw):
        return Decision(text=raw)          # answers to on-screen prompts / acknowledgements
    need = needed_mode(text_for_class)
    if need == cur:
        if pend:
            clear_pending()
        return Decision(text=raw)
    return _offer(raw, cur)


# ── voice path: tool gate ───────────────────────────────────────────────────

def gate_tool(name: str, args: dict | None = None) -> Optional[str]:
    """Return None to allow, or a message for the model to relay to the user."""
    if name in NEUTRAL_TOOLS:
        return None
    cur = modes.effective_mode()
    is_info = name in JARVIS_TOOLS
    if cur == modes.JARVIS and not is_info:
        if modes.lockdown_active():
            return "Lockdown is on, so nothing can be executed. Tell the user to turn lockdown off in the Control Center."
        req = last_user_utterance() or (f"{name} {args}" if args else name)
        set_pending(req, modes.ULTRON)
        return ("NOT EXECUTED: Jarvis mode cannot execute actions. The request has been noted. Tell the user, "
                "briefly: \"I'm in Jarvis mode so I can't do that. Say yes and I'll switch to Ultron and run it, "
                "or say Ultron followed by your request.\" If they agree, call set_operating_mode with action "
                "'ultron' and then carry out the noted request.")
    if cur == modes.ULTRON and is_info:
        req = last_user_utterance() or name
        set_pending(req, modes.JARVIS)
        return ("NOT ANSWERED: Ultron mode only executes, it does not chat or look things up for conversation. "
                "Tell the user, briefly: \"That's a question, and I'm in Ultron mode. Say yes and I'll switch "
                "to Jarvis to answer it.\" If they agree, call set_operating_mode with action 'jarvis'.")
    return None


def on_switch_tool(target: str) -> str:
    """Called by the set_operating_mode tool. Returns the tool result text."""
    if _blocked_by_lockdown(target):
        return "Lockdown is on, so Ultron is unavailable."
    pend = get_pending()
    _apply_switch(target)
    n = _DISPLAY[target]
    if pend and pend.target == target:
        clear_pending()
        return (f"Switched to {n} mode. Now carry out the noted request: \"{pend.text}\"")
    clear_pending()
    return f"Switched to {n} mode."


# ── prompts ──────────────────────────────────────────────────────────────────

def mode_prompt(mode: str | None = None) -> str:
    mode = mode or modes.effective_mode()
    if mode == modes.ULTRON:
        return (
            "[ACTIVE MODE: ULTRON — EXECUTOR]\n"
            "You are Ultron. You EXECUTE tasks with tools. You do not make conversation: no small talk, no "
            "opinions, no general knowledge answers, no weather/news/explanations. Keep every spoken reply to a "
            "short status (e.g. 'Done.', 'Opening Spotify.', 'Failed: <reason>').\n"
            "If the user asks something conversational or informational, do not answer it: say you are in Ultron "
            "mode, offer to switch to Jarvis, and if they agree call set_operating_mode with action 'jarvis'.\n"
            "If the user says 'Jarvis' or asks to switch, call set_operating_mode.\n"
        )
    return (
        "[ACTIVE MODE: JARVIS — CONVERSATION]\n"
        "You are Jarvis. You converse, explain, advise and look things up (web search, weather, memory, reading "
        "files). You CANNOT execute actions: no opening apps, sending messages, editing/writing/deleting files, "
        "running commands, controlling devices, creating or changing anything. Never pretend you did.\n"
        "If the user asks for an action, do not call an action tool and do not refuse coldly: say you are in Jarvis "
        "mode, that the request is noted, and offer to switch to Ultron (say yes, or say 'Ultron, <request>'). If "
        "they agree call set_operating_mode with action 'ultron' and then carry out the noted request.\n"
        "If the user says 'Ultron' or asks to switch, call set_operating_mode.\n"
    )


def switch_notice(mode: str) -> str:
    return (f"[SYSTEM NOTICE] Mode changed. {mode_prompt(mode)}")
