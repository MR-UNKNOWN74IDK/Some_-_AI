"""core/lan_policy.py — network exposure switches (Settings -> Control Center).

Default is private: the phone gateway and web dashboard listen on localhost
only and new phones must be approved by the user.  Turning on LAN access is
required for Jarvis Connect pairing from another device.
"""
from __future__ import annotations


def _get(key, default):
    try:
        from memory import config_manager
        return config_manager.get_setting(key, default)
    except Exception:
        return default


def lan_enabled() -> bool:
    return bool(_get("allow_lan_access", False))


def bind_host() -> str:
    return "0.0.0.0" if lan_enabled() else "127.0.0.1"


def strict_pairing() -> bool:
    """True = every new device waits for approval (Echo behaviour). False = Evo's
    convenience auto-pairing of a returning platform."""
    return bool(_get("strict_pairing", True))
