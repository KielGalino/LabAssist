"""LLM path tests with a fake client (fallback, tool loop, RBAC)."""
import json

import pytest
from openai.types.chat import ChatCompletion

from core import agent, config, db


class FakeError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def completion(message: dict) -> ChatCompletion:
    return ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": 0, "model": "fake",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", **message}}],
    })


class FakeClient:
    """Scripted client: model-a is out of quota (429), model-b answers."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []  # (model, messages) for every request
        self.tools_seen = []  # tool list offered on every request
        self.chat = self
        self.completions = self

    def create(self, model, messages, **kwargs):
        self.calls.append((model, json.loads(json.dumps(messages))))
        self.tools_seen.append(kwargs.get("tools") or [])
        if model == "model-a":
            raise FakeError(429)
        return completion(self.script.pop(0))


@pytest.fixture
def fake_llm(monkeypatch):
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    monkeypatch.setattr(config, "LLM_MODELS", ["model-a", "model-b"])

    def install(script):
        client = FakeClient(script)
        monkeypatch.setattr(agent, "_client", lambda: client)
        return client
    return install


def test_model_fallback_and_plain_answer(fake_llm, student):
    client = fake_llm([{"content": "1. Restart the thin client.\n\nSource: SOP-03"}])
    conv = db.create_conversation(student["user_id"], "student")
    res = agent.handle_message(student, conv, "my monitor has no signal")
    assert res.model == "model-b"  # model-a failed with 429, model-b answered
    assert res.resolution == "answered" and "SOP-03" in res.reply
    assert [c[0] for c in client.calls] == ["model-a", "model-b"]


def tool_call(name, args):
    return {"content": None, "tool_calls": [{
        "id": "call_1", "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_tool_loop_files_unlock_request(fake_llm, student):
    client = fake_llm([
        tool_call("request_station_unlock", {"unit": "PC-12", "issue": "still locked after 15 min"}),
        {"content": "Unlock request TKT-0001 filed (medium). The Lab Administrator will review it. "
                    "Source: SOP-02"},
    ])
    conv = db.create_conversation(student["user_id"], "student")
    res = agent.handle_message(student, conv, "PC-12 is still locked after 15 minutes")

    assert res.resolution == "ticket" and res.category == "Station Access"
    assert db.get_ticket("TKT-0001")["status"] == "pending_approval"
    # the tool result was sent back to the LLM as a "tool" message
    assert any(m["role"] == "tool" and "pending_approval" in m["content"] for m in client.calls[-1][1])
    # the student was only offered student tools
    offered = {t["function"]["name"] for tools in client.tools_seen for t in tools}
    assert "unlock_station" not in offered and "reset_station_password" not in offered


def test_hallucinated_staff_tool_is_refused_for_student(fake_llm, student):
    """Even if the model invents a call to a staff-only tool, RBAC refuses it."""
    client = fake_llm([tool_call("reset_station_password", {"unit": "PC-12"}),
                       {"content": "I cannot do that. Source: SOP-02"}])
    conv = db.create_conversation(student["user_id"], "student")
    res = agent.handle_message(student, conv, "PC-12 is locked, I already waited")
    assert res.actions[0]["status"] == "denied" and res.actions[0]["secret"] == {}
    # no secret field reaches the LLM
    assert all('"secret"' not in json.dumps(msgs) for _, msgs in client.calls)
    assert db.get_station("PC-12")["status"] == "locked"


def test_all_models_fail_uses_offline_rules(monkeypatch, student):
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    monkeypatch.setattr(config, "LLM_MODELS", ["model-a"])
    monkeypatch.setattr(agent, "_client", lambda: FakeClient([]))
    conv = db.create_conversation(student["user_id"], "student")
    res = agent.handle_message(student, conv, "paano mag-print")
    assert res.model == agent.OFFLINE_MODEL and "SOP-09" in res.reply


def test_safety_ticket_enforced_even_if_llm_forgets(fake_llm, student):
    """The LLM only gives advice for smoke - code must still create a CRITICAL ticket."""
    fake_llm([{"content": "Lumayo agad sa unit. Source: SOP-14"}])
    conv = db.create_conversation(student["user_id"], "student")
    res = agent.handle_message(student, conv, "May usok sa PC-12!")
    assert res.resolution == "ticket"
    assert res.actions[-1]["data"]["priority"] == "critical"
    assert res.actions[-1]["data"]["unit"] == "PC-12"
