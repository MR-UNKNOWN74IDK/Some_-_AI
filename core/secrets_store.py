"""
core/secrets_store.py — encrypted vault for API keys and other credentials.

WHY THIS EXISTS
    Both source projects kept credentials in plaintext JSON on disk
    (config/api_keys.json, discord_bot.json, spotify-config.json,
    email_credentials.json).  The compiled product has no config folder the
    user is meant to edit, so those values are entered in the Settings UI
    (core/ultra_settings.py) and kept here instead.

HOW IT WORKS
    * On Windows the vault is encrypted with DPAPI (CryptProtectData), i.e.
      bound to the current Windows user account.  Nothing is stored in clear
      text and nothing needs a master password.
    * ~35 modules across the code base still do
          json.load(open(".../api_keys.json"))
      so instead of rewriting each one, `install()` makes those *specific
      file names* virtual: reads are served from the vault, writes go to the
      vault, `.exists()` reflects whether the vault holds data.  No file is
      ever created on disk for them.
    * Legacy plaintext copies found on disk are imported once and then
      overwritten and deleted (`migrate_legacy`).

NON-WINDOWS NOTE
    DPAPI only exists on Windows.  On other platforms (development / CI) the
    vault falls back to a Fernet key stored next to the vault file.  That is
    NOT a security boundary — it only keeps the tests honest.  The product is
    Windows-only.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import pathlib
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from core.user_paths import get_user_data_dir

# File names that are served from the vault instead of the disk.
VIRTUAL_FILES = {
    "api_keys.json",
    "discord_bot.json",
    "spotify-config.json",
    "email_credentials.json",
}
PRIMARY = "api_keys.json"

# Keys in api_keys.json that hold secrets (used for masking in the UI/logs).
SECRET_KEYS = {
    "gemini_api_key", "openrouter_api_key", "anthropic_api_key", "carto_api_key",
    "instagram_password", "instagram_sessionid", "bot_token",
    "client_secret", "spotify_client_secret", "weather_api_key",
}

_ENTROPY = b"JarvisUltron.vault.v1"
_MAGIC = b"BUV1"

_lock = threading.RLock()
_cache: Optional[Dict[str, str]] = None
_installed = False

_real_open = builtins.open
_real_io_open = io.open
_real_path_exists = pathlib.Path.exists
_real_path_is_file = pathlib.Path.is_file
_real_os_exists = os.path.exists
_real_os_isfile = os.path.isfile


# ───────────────────────────── encryption backends ─────────────────────────

def _vault_file() -> Path:
    d = get_user_data_dir() / "vault"
    d.mkdir(parents=True, exist_ok=True)
    return d / "secrets.bin"


def backend_name() -> str:
    return "windows-dpapi" if sys.platform == "win32" else "fernet-dev-fallback"


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(b: bytes):
        buf = ctypes.create_string_buffer(b, len(b))
        return DATA_BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    b_in, _keep1 = blob(data)
    b_ent, _keep2 = blob(_ENTROPY)
    b_out = DATA_BLOB()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    ok = fn(ctypes.byref(b_in), None, ctypes.byref(b_ent), None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(b_out))
    if not ok:
        raise OSError(f"DPAPI {'protect' if protect else 'unprotect'} failed "
                      f"(error {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(b_out.pbData, b_out.cbData)
    finally:
        kernel32.LocalFree(b_out.pbData)


def _fernet():
    from cryptography.fernet import Fernet
    kf = _vault_file().with_name(".devkey")
    if kf.exists():
        key = kf.read_bytes()
    else:
        key = Fernet.generate_key()
        kf.write_bytes(key)
    return Fernet(key)


def _encrypt(plain: bytes) -> bytes:
    if sys.platform == "win32":
        return _MAGIC + _dpapi(plain, True)
    return _MAGIC + _fernet().encrypt(plain)


def _decrypt(blob: bytes) -> bytes:
    if not blob.startswith(_MAGIC):
        raise ValueError("unrecognised vault format")
    body = blob[len(_MAGIC):]
    if sys.platform == "win32":
        return _dpapi(body, False)
    return _fernet().decrypt(body)


# ───────────────────────────── vault load / save ───────────────────────────

def _load() -> Dict[str, str]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        vf = _vault_file()
        data: Dict[str, str] = {}
        if vf.exists():
            try:
                with _real_open(vf, "rb") as f:
                    raw = f.read()
                data = json.loads(_decrypt(raw).decode("utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except Exception as exc:  # corrupt / other user's vault: start empty, keep file
                print(f"[VAULT] could not read vault ({exc}); starting empty.")
                data = {}
        _cache = data
        return _cache


def _save() -> None:
    with _lock:
        vf = _vault_file()
        blob = _encrypt(json.dumps(_load()).encode("utf-8"))
        tmp = vf.with_suffix(".tmp")
        with _real_open(tmp, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, vf)


def reset_cache_for_tests() -> None:
    global _cache
    with _lock:
        _cache = None


# ───────────────────────────── public API ──────────────────────────────────

def get_all(name: str = PRIMARY) -> Dict[str, Any]:
    with _lock:
        text = _load().get(name)
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def set_all(data: Dict[str, Any], name: str = PRIMARY) -> None:
    with _lock:
        _load()[name] = json.dumps(data)
        _save()


def get(key: str, default: Any = "", name: str = PRIMARY) -> Any:
    return get_all(name).get(key, default)


def set_many(values: Dict[str, Any], name: str = PRIMARY) -> None:
    cur = get_all(name)
    cur.update(values)
    set_all(cur, name)


def set(key: str, value: Any, name: str = PRIMARY) -> None:  # noqa: A001 (intentional)
    set_many({key: value}, name)


def has_data(name: str = PRIMARY) -> bool:
    with _lock:
        return bool(_load().get(name))


def mask(value: str) -> str:
    value = value or ""
    if len(value) <= 8:
        return "•" * len(value)
    return value[:3] + "•" * 8 + value[-3:]


def wipe(name: Optional[str] = None) -> None:
    """Delete one virtual file's contents, or the whole vault."""
    with _lock:
        if name is None:
            _load().clear()
        else:
            _load().pop(name, None)
        _save()


# ───────────────────────────── legacy migration ────────────────────────────

def _shred(path: Path) -> None:
    try:
        size = path.stat().st_size
        with _real_open(path, "r+b") as f:
            f.write(b"\x00" * size)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass
    try:
        os.remove(path)
    except Exception:
        pass


def migrate_legacy(extra_dirs: Iterable[Path] = ()) -> int:
    """Import plaintext copies of virtual files, then overwrite + delete them.
    Returns the number of files migrated.  (On SSDs an overwrite is not a
    guarantee; rotating the keys afterwards is the only real remedy.)"""
    cfg = get_user_data_dir() / "config"
    dirs = [cfg, *extra_dirs]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        dirs.append(Path(base) / "config")
    migrated = 0
    for d in dirs:
        for name in VIRTUAL_FILES:
            p = Path(d) / name
            try:
                if not _real_path_exists(p):
                    continue
                with _real_open(p, "r", encoding="utf-8") as f:
                    text = f.read()
                incoming = json.loads(text)
                if isinstance(incoming, dict):
                    merged = get_all(name)
                    # vault wins on conflicts; legacy only fills gaps
                    for k, v in incoming.items():
                        if k not in merged or merged[k] in ("", None):
                            merged[k] = v
                    set_all(merged, name)
                    _shred(p)
                    migrated += 1
            except Exception as exc:
                print(f"[VAULT] legacy import skipped for {p}: {exc}")
    return migrated


# ───────────────────────────── virtual-file shim ───────────────────────────

def _virtual_name(path: Any) -> Optional[str]:
    try:
        base = os.path.basename(os.fspath(path)).lower()
    except Exception:
        return None
    return base if base in VIRTUAL_FILES else None


class _VaultWriter(io.StringIO):
    def __init__(self, name: str, initial: str = ""):
        super().__init__()
        self._vname = name
        self._flushed = False
        if initial:
            self.write(initial)

    def close(self):
        if not self.closed and not self._flushed:
            self._flushed = True
            text = self.getvalue()
            try:
                json.loads(text)  # only persist valid JSON
                with _lock:
                    _load()[self._vname] = text
                    _save()
            except Exception as exc:
                print(f"[VAULT] refused to store invalid content for {self._vname}: {exc}")
        super().close()


def _virtual_open(name: str, mode: str, encoding: Optional[str]):
    binary = "b" in mode
    if "r" in mode and "+" not in mode:
        with _lock:
            text = _load().get(name)
        if text is None:
            raise FileNotFoundError(2, "No such file or directory (vault)", name)
        return io.BytesIO(text.encode("utf-8")) if binary else io.StringIO(text)
    initial = ""
    if "a" in mode:
        with _lock:
            initial = _load().get(name, "")
    return _VaultWriter(name, initial)


def _patched_open(file, mode="r", *args, **kwargs):
    name = _virtual_name(file) if isinstance(file, (str, bytes, os.PathLike)) else None
    if name:
        enc = kwargs.get("encoding") or (args[1] if len(args) > 1 else None)
        return _virtual_open(name, mode, enc)
    return _real_open(file, mode, *args, **kwargs)


def _patched_path_exists(self, *a, **k):
    name = _virtual_name(self)
    return has_data(name) if name else _real_path_exists(self, *a, **k)


def _patched_path_is_file(self, *a, **k):
    name = _virtual_name(self)
    return has_data(name) if name else _real_path_is_file(self, *a, **k)


def _patched_os_exists(path):
    name = _virtual_name(path)
    return has_data(name) if name else _real_os_exists(path)


def _patched_os_isfile(path):
    name = _virtual_name(path)
    return has_data(name) if name else _real_os_isfile(path)


def install() -> None:
    """Idempotent.  Call once, as early as possible in main.py."""
    global _installed
    with _lock:
        if _installed:
            return
        builtins.open = _patched_open
        io.open = _patched_open
        pathlib.Path.exists = _patched_path_exists
        pathlib.Path.is_file = _patched_path_is_file
        os.path.exists = _patched_os_exists
        os.path.isfile = _patched_os_isfile
        _installed = True
    try:
        n = migrate_legacy()
        if n:
            print(f"[VAULT] migrated {n} plaintext credential file(s) into the encrypted vault.")
    except Exception as exc:
        print(f"[VAULT] migration error: {exc}")


def uninstall() -> None:
    """Test helper: restore the real file functions."""
    global _installed
    with _lock:
        builtins.open = _real_open
        io.open = _real_io_open
        pathlib.Path.exists = _real_path_exists
        pathlib.Path.is_file = _real_path_is_file
        os.path.exists = _real_os_exists
        os.path.isfile = _real_os_isfile
        _installed = False
