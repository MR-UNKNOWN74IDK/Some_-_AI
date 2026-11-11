"""
ultra_control_center.py — Settings -> Control Center.

Everything that used to live in text files lives here: API keys (stored in the
encrypted vault, never written to disk in clear), the Jarvis/Ultron switch,
every safety layer, network exposure, and the safety audit log.
"""
from __future__ import annotations

import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget,
)

from core import modes, safety_stack, secrets_store
from memory import config_manager

# (vault file, json key, label, is_secret)
KEY_FIELDS = [
    ("api_keys.json", "gemini_api_key", "Google Gemini API key (voice + vision)", True),
    ("api_keys.json", "openrouter_api_key", "OpenRouter API key (fallback)", True),
    ("api_keys.json", "anthropic_api_key", "Anthropic API key", True),
    ("api_keys.json", "carto_api_key", "Carto / maps API key", True),
    ("api_keys.json", "instagram_username", "Instagram username", False),
    ("api_keys.json", "instagram_password", "Instagram password", True),
    ("spotify-config.json", "clientId", "Spotify client ID", False),
    ("spotify-config.json", "clientSecret", "Spotify client secret", True),
    ("discord_bot.json", "bot_token", "Discord bot token", True),
]

LAYERS = [
    ("tool_gate", "L2  Tool gate — ask before risky tools (Jarvis) / audit them (Ultron)"),
    ("code_scan", "L1  Code scan warnings for skills and self-heal patches"),
    ("sandbox_env", "L3  Scrubbed environment for skill test runs"),
    ("integrity", "L4  Quarantine forged skills edited on disk"),
    ("autonomy_budget", "L5  Hourly cap on autonomous heals / skill forging"),
]

TOGGLES = [
    ("sound_effects_enabled", "Sound effects", True),
    ("push_to_talk_enabled", "Push-to-talk", False),
    ("check_updates_on_startup", "Check for updates on startup", True),
    ("launch_minimized", "Launch minimized", False),
    ("offline_mode_enabled", "Offline mode (local model only)", False),
    ("attention_message_prompts", "Prompt me about incoming messages", True),
    ("attention_call_prompts", "Prompt me about incoming calls", True),
]


class ControlCenter(QDialog):
    def __init__(self, parent=None, start_tab: int = 0, on_mode_change=None):
        super().__init__(parent)
        self.setWindowTitle("Jarvis Ultron — Control Center")
        self.resize(720, 640)
        self._on_mode_change = on_mode_change
        self._edits: dict = {}
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)
        tabs.addTab(self._tab_keys(), "API Keys")
        tabs.addTab(self._tab_mode(), "Mode & Safety")
        tabs.addTab(self._tab_network(), "Network")
        tabs.addTab(self._tab_general(), "General")
        tabs.addTab(self._tab_audit(), "Audit log")
        tabs.setCurrentIndex(start_tab)

    # ── API keys ────────────────────────────────────────────────────────
    def _tab_keys(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        info = QLabel(f"Keys are encrypted with {secrets_store.backend_name()} and are not stored in any text file. "
                      "Leave a field untouched to keep its saved value; saved keys are shown masked.")
        info.setWordWrap(True)
        v.addWidget(info)
        form = QFormLayout()
        for vault, key, label, secret in KEY_FIELDS:
            row = QHBoxLayout()
            e = QLineEdit()
            cur = str(secrets_store.get(key, "", name=vault) or "")
            e.setPlaceholderText(secrets_store.mask(cur) if cur and secret else ("(not set)" if not cur else ""))
            if not secret:
                e.setText(cur)
            else:
                e.setEchoMode(QLineEdit.EchoMode.Password)
            show = QPushButton("Show")
            show.setCheckable(True)
            show.setFixedWidth(56)
            show.toggled.connect(lambda on, ed=e: ed.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
            row.addWidget(e)
            if secret:
                row.addWidget(show)
            form.addRow(label, row)
            self._edits[(vault, key)] = (e, secret)
        v.addLayout(form)
        btns = QHBoxLayout()
        save = QPushButton("Save keys")
        save.clicked.connect(self._save_keys)
        clear = QPushButton("Clear selected provider…")
        clear.clicked.connect(self._clear_key)
        btns.addWidget(save)
        btns.addWidget(clear)
        v.addLayout(btns)
        self._key_status = QLabel("")
        v.addWidget(self._key_status)
        v.addStretch(1)
        return w

    def _save_keys(self):
        changed = 0
        for (vault, key), (edit, secret) in self._edits.items():
            text = edit.text().strip()
            if secret and not text:
                continue                      # untouched -> keep saved value
            if not secret and text == str(secrets_store.get(key, "", name=vault) or ""):
                continue
            secrets_store.set(key, text, name=vault)
            changed += 1
            if secret:
                edit.clear()
                edit.setPlaceholderText(secrets_store.mask(text))
        secrets_store.set("os_system", "Windows")
        safety_stack.audit("keys_updated", layer="vault", detail=f"{changed} field(s)")
        self._key_status.setText(f"Saved {changed} change(s). Restart Jarvis if a provider was already connected.")

    def _clear_key(self):
        if QMessageBox.question(self, "Clear all keys",
                                "Remove ALL stored API keys and credentials from this PC?") \
                != QMessageBox.StandardButton.Yes:
            return
        secrets_store.wipe()
        safety_stack.audit("vault_wiped", layer="vault")
        self._key_status.setText("All stored credentials removed.")

    # ── mode & safety ───────────────────────────────────────────────────
    def _tab_mode(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self._mode_label = QLabel()
        self._mode_label.setWordWrap(True)
        v.addWidget(self._mode_label)
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Jarvis — conversation & information only (cannot execute)", modes.JARVIS)
        self._mode_combo.addItem("Ultron — executes tasks, self-heals, forges skills (does not chat)", modes.ULTRON)
        self._mode_combo.setCurrentIndex(0 if modes.get_mode() == modes.JARVIS else 1)
        self._mode_combo.currentIndexChanged.connect(self._mode_changed)
        v.addWidget(self._mode_combo)
        self._lockdown = QCheckBox("LOCKDOWN — Jarvis only: nothing can be executed, no autonomous features")
        self._lockdown.setChecked(modes.lockdown_active())
        self._lockdown.toggled.connect(self._lockdown_changed)
        v.addWidget(self._lockdown)
        v.addWidget(QLabel("\nSafety layers"))
        l0 = QCheckBox("L0  Hard blocks (disk wipes, remote-code one-liners, protected paths) — always on")
        l0.setChecked(True)
        l0.setEnabled(False)
        v.addWidget(l0)
        for key, label in LAYERS:
            cb = QCheckBox(label)
            cb.setChecked(safety_stack.layer_enabled(key))
            cb.toggled.connect(lambda on, k=key: self._set(f"safety_layer_{k}", on))
            v.addWidget(cb)
        v.addWidget(QLabel("\nRisky tools that may run in Ultron without a confirmation (comma separated):"))
        self._trusted = QLineEdit(", ".join(sorted(safety_stack.trusted_tools())))
        self._trusted.editingFinished.connect(lambda: self._set("safety_trusted_tools", self._trusted.text()))
        v.addWidget(self._trusted)
        note = QLabel("Messages to other people, posting, unlocking devices and deletions always ask, in both modes.")
        note.setWordWrap(True)
        v.addWidget(note)
        v.addStretch(1)
        self._refresh_mode_label()
        return w

    def _refresh_mode_label(self):
        self._mode_label.setText(f"Current: {modes.banner()}")

    def _mode_changed(self, _i):
        modes.set_mode(self._mode_combo.currentData())
        self._refresh_mode_label()
        if self._on_mode_change:
            self._on_mode_change(modes.effective_mode())

    def _lockdown_changed(self, on):
        self._set("safety_lockdown", on)
        safety_stack.audit("lockdown", layer="modes", detail="on" if on else "off")
        self._refresh_mode_label()
        if self._on_mode_change:
            self._on_mode_change(modes.effective_mode())

    # ── network ─────────────────────────────────────────────────────────
    def _tab_network(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        lan = QCheckBox("Allow other devices on my network (Jarvis Connect phone pairing, web dashboard)")
        lan.setChecked(bool(config_manager.get_setting("allow_lan_access", False)))
        lan.toggled.connect(lambda on: self._set("allow_lan_access", on))
        strict = QCheckBox("Require my approval for every new device (recommended)")
        strict.setChecked(bool(config_manager.get_setting("strict_pairing", True)))
        strict.toggled.connect(lambda on: self._set("strict_pairing", on))
        v.addWidget(lan)
        v.addWidget(strict)
        n = QLabel("Off by default: the gateway and dashboard listen on this PC only. "
                   "There is no TLS on the gateway, so only enable LAN access on a network you trust. "
                   "Changes apply after restarting Jarvis.")
        n.setWordWrap(True)
        v.addWidget(n)
        v.addStretch(1)
        return w

    # ── general ─────────────────────────────────────────────────────────
    def _tab_general(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        for key, label, default in TOGGLES:
            cb = QCheckBox(label)
            cb.setChecked(bool(config_manager.get_setting(key, default)))
            cb.toggled.connect(lambda on, k=key: self._set(k, on))
            v.addWidget(cb)
        form = QFormLayout()
        self._provider = QComboBox()
        self._provider.addItems(["Gemini", "OpenRouter", "Local"])
        self._provider.setCurrentText(str(config_manager.get_setting("default_ai_provider", "Gemini")))
        self._provider.currentTextChanged.connect(lambda t: self._set("default_ai_provider", t))
        form.addRow("Default AI provider", self._provider)
        self._local_url = QLineEdit(str(config_manager.get_setting("local_ai_url", "http://localhost:11434/v1")))
        self._local_url.editingFinished.connect(lambda: self._set("local_ai_url", self._local_url.text()))
        form.addRow("Local AI URL", self._local_url)
        self._local_model = QLineEdit(str(config_manager.get_setting("local_ai_model", "qwen2.5:3b")))
        self._local_model.editingFinished.connect(lambda: self._set("local_ai_model", self._local_model.text()))
        form.addRow("Local AI model", self._local_model)
        v.addLayout(form)
        v.addStretch(1)
        return w

    # ── audit ───────────────────────────────────────────────────────────
    def _tab_audit(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self._audit = QPlainTextEdit()
        self._audit.setReadOnly(True)
        v.addWidget(self._audit)
        b = QPushButton("Refresh")
        b.clicked.connect(self._load_audit)
        v.addWidget(b)
        self._load_audit()
        return w

    def _load_audit(self):
        lines = [f"{r.get('ts')}  [{r.get('mode')}] {r.get('layer', ''):>5} {r.get('event')} "
                 f"{r.get('tool', '')} {r.get('verdict', '')} {r.get('detail', '')}"
                 for r in reversed(safety_stack.read_audit(300))]
        self._audit.setPlainText("\n".join(lines) or "No safety events yet.")

    @staticmethod
    def _set(key, value):
        config_manager.set_setting(key, value)


def open_control_center(parent=None, start_tab: int = 0, on_mode_change=None):
    dlg = ControlCenter(parent, start_tab, on_mode_change)
    dlg.exec()
