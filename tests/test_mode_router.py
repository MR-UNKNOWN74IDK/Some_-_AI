"""Jarvis talks, Ultron acts — routing and tool gate."""
import pytest


@pytest.fixture()
def r(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from memory import config_manager
    monkeypatch.setattr(config_manager, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(config_manager, "SETTINGS_FILE", tmp_path / "cfg" / "app_settings.json")
    from core import mode_router, modes
    mode_router.clear_pending()
    mode_router.note_user_utterance("")
    modes.set_mode("jarvis")
    return mode_router, modes


def test_jarvis_action_is_noted_not_executed(r):
    mr, modes = r
    d = mr.route_text("Jarvis, please open Spotify")
    assert d.stop and not d.text and "Ultron, please open Spotify" in d.reply
    assert modes.get_mode() == "jarvis" and mr.get_pending().text == "please open Spotify"


def test_switch_command_forwards_pending_request(r):
    mr, modes = r
    mr.route_text("Jarvis, please open Spotify")
    d = mr.route_text("switch to Ultron mode")
    assert modes.get_mode() == "ultron" and d.text == "please open Spotify" and not d.stop
    assert mr.get_pending() is None


def test_yes_also_forwards(r):
    mr, modes = r
    mr.route_text("open spotify")
    d = mr.route_text("yes")
    assert modes.get_mode() == "ultron" and d.text == "open spotify"


def test_addressing_ultron_by_name_switches_and_runs(r):
    mr, modes = r
    d = mr.route_text("Ultron, please open Spotify")
    assert modes.get_mode() == "ultron" and d.text == "please open Spotify" and d.switched_to == "ultron"


def test_aldron_spelling_is_accepted(r):
    mr, modes = r
    d = mr.route_text("Aldron, open notepad")
    assert modes.get_mode() == "ultron" and d.text == "open notepad"
    mr.route_text("switch to jarvis")
    assert modes.get_mode() == "jarvis"
    mr.route_text("go to Aldron")
    assert modes.get_mode() == "ultron"


def test_idle_switch_without_pending_does_nothing_else(r):
    mr, modes = r
    d = mr.route_text("switch to Ultron")
    assert d.stop and not d.text and modes.get_mode() == "ultron"
    d = mr.route_text("Jarvis mode")
    assert d.stop and modes.get_mode() == "jarvis"


def test_ultron_chat_offers_jarvis_and_forwards(r):
    mr, modes = r
    modes.set_mode("ultron")
    d = mr.route_text("what is the weather")
    assert d.stop and "Jarvis" in d.reply and mr.get_pending().target == "jarvis"
    d = mr.route_text("switch to Jarvis")
    assert modes.get_mode() == "jarvis" and d.text == "what is the weather"


def test_matching_requests_pass_through(r):
    mr, modes = r
    assert mr.route_text("what's the weather like?").text == "what's the weather like?"
    assert mr.route_text("Jarvis, explain recursion").text == "explain recursion"
    modes.set_mode("ultron")
    assert mr.route_text("open notepad").text == "open notepad"
    assert mr.route_text("can you please close chrome").text == "can you please close chrome"


def test_no_clears_pending(r):
    mr, modes = r
    mr.route_text("delete my temp files")
    d = mr.route_text("no")
    assert d.stop and mr.get_pending() is None and modes.get_mode() == "jarvis"
    assert mr.route_text("yes").text == "yes"  # nothing pending: ordinary chat text


def test_lockdown_blocks_ultron(r):
    mr, modes = r
    from memory import config_manager
    config_manager.set_setting("safety_lockdown", True)
    assert "Lockdown" in mr.route_text("open spotify").reply
    assert "Lockdown" in mr.route_text("switch to ultron").reply
    assert modes.effective_mode() == "jarvis"


@pytest.mark.parametrize("text,kind", [
    ("open spotify", "action"), ("please send a message to mom", "action"),
    ("can you turn off the lights", "action"), ("what time is it", "chat"),
    ("who wrote hamlet?", "chat"), ("tell me a joke", "chat"), ("how do I open a file in python", "chat"),
    ("how are you", "chat"), ("delete the downloads folder", "action"), ("search the web for pizza", "chat"),
])
def test_classification(r, text, kind):
    mr, _ = r
    assert mr.classify(text) == kind


def test_tool_gate_voice_path(r):
    mr, modes = r
    mr.note_user_utterance("open spotify")
    assert "NOT EXECUTED" in mr.gate_tool("open_app", {"app_name": "spotify"})
    assert mr.get_pending().text == "open spotify"
    assert mr.gate_tool("weather_report", {}) is None
    assert mr.gate_tool("set_operating_mode", {"action": "ultron"}) is None
    msg = mr.on_switch_tool("ultron")
    assert "open spotify" in msg and modes.get_mode() == "ultron"
    assert mr.gate_tool("open_app", {}) is None
    mr.note_user_utterance("what's the weather")
    assert "NOT ANSWERED" in mr.gate_tool("weather_report", {})
    assert "weather" in mr.on_switch_tool("jarvis")


def test_every_declared_tool_is_classified_sanely(r):
    """Anything not explicitly an info tool is Ultron-only; set the info list on purpose."""
    mr, _ = r
    for t in ("bash", "file_write", "send_message", "skill_forge", "computer_control", "reminder", "undo"):
        assert t not in mr.JARVIS_TOOLS


def test_prompt_answers_and_acknowledgements_are_not_routed(r):
    mr, modes = r
    modes.set_mode("ultron")
    for t in ("yes", "no", "cancel", "thanks", "okay"):
        d = mr.route_text(t)
        assert d.text == t and not d.reply, t
