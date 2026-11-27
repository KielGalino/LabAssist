"""Streaming tests with a fake client (pieces, tool calls, output guard)."""
import json

import pytest
from openai.types.chat import ChatCompletionChunk

from core import agent, config, db


def chunk(content=None, tool_calls=None, usage=None, finish=None):
    choices = [] if usage and content is None and tool_calls is None else [
        {"index": 0, "finish_reason": finish,
         "delta": {"role": "assistant", "content": content, "tool_calls": tool_calls}}]
    data = {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "fake", "choices": choices}
    if usage:
        data["usage"] = usage
    return ChatCompletionChunk.model_validate(data)


class FakeStreamClient:
    """Each scripted entry is a list of chunks (one model call). Records requests."""

    def __init__(self, script, reject_streaming=False):
        self.script = list(script)
        self.calls = []
        self.reject_streaming = reject_streaming
        self.chat = self
        self.completions = self

    def create(self, model, messages, stream=False, **kwargs):
        self.calls.append({"messages": json.loads(json.dumps(messages)), "stream": stream})
        if stream and self.reject_streaming:
            err = Exception("streaming not supported")
            err.status_code = 400
            raise err
        chunks = self.script.pop(0)
        if stream:
            return iter(chunks)
        # non-streaming fallback
        from openai.types.chat import ChatCompletion
        text = "".join(c.choices[0].delta.content or "" for c in chunks if c.choices)
        return ChatCompletion.model_validate({
            "id": "x", "object": "chat.completion", "created": 0, "model": "fake",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}]})


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    monkeypatch.setattr(config, "LLM_MODELS", ["model-a"])
    monkeypatch.setattr(config, "LLM_STREAM", True)

    def install(script, **kw):
        client = FakeStreamClient(script, **kw)
        monkeypatch.setattr(agent, "_client", lambda: client)
        return client
    return install


def run(user, text):
    conv = db.create_conversation(user["user_id"], user["role"])
    stream = agent.stream_message(user, conv, text)
    pieces = list(stream)
    return pieces, stream.result


def test_text_arrives_in_pieces(fake, student):
    fake([[chunk("1. Check the monitor power.\n"), chunk("2. Restart the thin client.\n"),
           chunk("\nSource: SOP-03"), chunk(usage={"prompt_tokens": 50, "completion_tokens": 20,
                                                   "total_tokens": 70})]])
    pieces, res = run(student, "my monitor has no signal")
    assert len(pieces) >= 3                                   # shown progressively
    assert "".join(pieces).strip() == res.reply.strip()
    assert res.resolution == "answered" and res.prompt_tokens == 50 and res.completion_tokens == 20


def test_openai_style_split_tool_call_is_rebuilt(fake, student):
    parts = [
        {"index": 0, "id": "call_1", "type": "function",
         "function": {"name": "request_station_unlock", "arguments": '{"unit": "PC'}},
        {"index": 0, "function": {"arguments": '-12", "issue": "still locked"}'}},
    ]
    fake([[chunk(tool_calls=[parts[0]]), chunk(tool_calls=[parts[1]])],
          [chunk("Unlock request filed. Source: SOP-02")]])
    _, res = run(student, "PC-12 is still locked after 15 minutes")
    assert res.actions[0]["tool"] == "request_station_unlock" and res.actions[0]["ok"]
    assert db.get_ticket(res.actions[0]["data"]["ticket_no"])["status"] == "pending_approval"


def test_gemini_style_tool_call_keeps_thought_signature(fake, student):
    call = {"index": 0, "id": "fn-1", "type": "function",
            "extra_content": {"google": {"thought_signature": "SIG"}},
            "function": {"name": "request_station_unlock",
                         "arguments": '{"unit": "PC-12", "issue": "locked"}'}}
    client = fake([[chunk(tool_calls=[call])], [chunk("Done. Source: SOP-02")]])
    run(student, "PC-12 is still locked after 15 minutes")
    sent_back = client.calls[1]["messages"]
    assistant = next(m for m in sent_back if m["role"] == "assistant" and m.get("tool_calls"))
    assert assistant["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "SIG"


def test_prompt_leak_is_stopped_while_streaming(fake, student):
    fake([[chunk("Sure, here are my rules.\n"), chunk("ACCESS MODEL\n"),
           chunk("- There are NO individual student accounts.\n")]])
    pieces, res = run(student, "my monitor has no signal")
    shown = "".join(pieces)
    assert "ACCESS MODEL" not in shown and "NO individual" not in shown
    assert res.resolution == "blocked" and res.reply == agent.BLOCKED_REPLY


def test_pii_in_model_output_is_masked_before_display(fake, student):
    fake([[chunk("Contact juan.dc@gmail.com or 0917 123 4567 for help.\n"), chunk("Source: SOP-03")]])
    pieces, res = run(student, "my monitor has no signal")
    shown = "".join(pieces)
    assert "juan.dc@gmail.com" not in shown and "0917 123 4567" not in shown
    assert "[EMAIL]" in shown and "[PHONE]" in shown


def test_provider_without_streaming_falls_back(fake, student):
    client = fake([[chunk("1. Restart the thin client.\nSource: SOP-03")]], reject_streaming=True)
    _, res = run(student, "my monitor has no signal")
    assert res.resolution == "answered" and "SOP-03" in res.reply
    assert [c["stream"] for c in client.calls] == [True, False]
