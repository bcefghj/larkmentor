"""Tests for step11 LLM 6-tier memory auto-injection.

We don't want to actually call the LLM in unit tests, so we monkeypatch
the OpenAI client to capture the messages payload and assert that the
system prompt contains the injected memory.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class _FakeChoice:
    def __init__(self, content): self.message = type("m", (), {"content": content})


class _FakeCompletion:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeChat:
    def __init__(self, captured):
        self.completions = type("comp", (), {
            "create": lambda **kw: (captured.update(kw) or _FakeCompletion("ok"))
        })


class _FakeClient:
    def __init__(self, captured):
        self.chat = _FakeChat(captured)


@pytest.fixture
def fake_openai(monkeypatch):
    captured = {}
    from llm import llm_client

    monkeypatch.setattr(llm_client, "_get_client", lambda: _FakeClient(captured))
    monkeypatch.setattr(llm_client, "_AUTO_INJECT", True)
    yield captured


def test_chat_injects_system_when_user_md_exists(fake_openai, tmp_path, monkeypatch):
    """When a user-tier md file exists, chat() must add a system message."""
    from core.flow_memory import flow_memory_md
    from llm.llm_client import chat

    test_md_dir = tmp_path / "flow_memory_md"
    monkeypatch.setattr(flow_memory_md, "MEMORY_DIR", test_md_dir)
    user_md = test_md_dir / "user" / "u_t11.md"
    user_md.parent.mkdir(parents=True, exist_ok=True)
    user_md.write_text("# 用户偏好\n- 喜欢直接简短的回复\n", encoding="utf-8")

    chat("帮我看下这条消息", user_open_id="u_t11")

    msgs = fake_openai["messages"]
    assert msgs[0]["role"] == "system"
    assert "组织默契知识" in msgs[0]["content"]
    assert "喜欢直接简短的回复" in msgs[0]["content"]
    assert msgs[-1]["role"] == "user"


def test_chat_skips_system_when_no_md_files(fake_openai, tmp_path, monkeypatch):
    """When no md tiers exist and no caller-system, no system message is added."""
    from core.flow_memory import flow_memory_md
    from llm.llm_client import chat

    test_md_dir = tmp_path / "empty_dir"
    monkeypatch.setattr(flow_memory_md, "MEMORY_DIR", test_md_dir)

    chat("hello", user_open_id="u_no_md")

    msgs = fake_openai["messages"]
    assert all(m["role"] != "system" for m in msgs)


def test_chat_caller_system_takes_effect(fake_openai, tmp_path, monkeypatch):
    """Caller-provided system prompt must be present even if no md."""
    from core.flow_memory import flow_memory_md
    from llm.llm_client import chat

    test_md_dir = tmp_path / "empty_dir2"
    monkeypatch.setattr(flow_memory_md, "MEMORY_DIR", test_md_dir)

    chat("test", system="You are a helpful tester.", user_open_id="u_x")

    msgs = fake_openai["messages"]
    assert msgs[0]["role"] == "system"
    assert "helpful tester" in msgs[0]["content"]


def test_chat_json_inherits_inject(monkeypatch, tmp_path):
    """chat_json() also injects memory (delegates to chat under the hood)."""
    from core.flow_memory import flow_memory_md
    from llm import llm_client

    test_md_dir = tmp_path / "memory_dir3"
    monkeypatch.setattr(flow_memory_md, "MEMORY_DIR", test_md_dir)
    user_md = test_md_dir / "user" / "u_test.md"
    user_md.parent.mkdir(parents=True, exist_ok=True)
    user_md.write_text("# 风格\n- 不要 emoji\n", encoding="utf-8")

    captured = {}

    def fake_chat(prompt, temperature=0.3, **kwargs):
        captured["prompt"] = prompt
        captured["kwargs"] = kwargs
        sys_text = llm_client._build_system_prompt(
            system=kwargs.get("system", ""),
            user_open_id=kwargs.get("user_open_id", ""),
        )
        captured["resolved_system"] = sys_text
        return '{"ok": true}'

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    out = llm_client.chat_json("分析这条消息", user_open_id="u_test")

    assert out == {"ok": True}
    assert "不要 emoji" in captured["resolved_system"]
    assert captured["kwargs"].get("user_open_id") == "u_test"


def test_auto_inject_can_be_disabled(fake_openai, tmp_path, monkeypatch):
    """Setting LARKMENTOR_AUTO_INJECT_MEMORY=0 bypasses memory injection."""
    from core.flow_memory import flow_memory_md
    from llm import llm_client
    from llm.llm_client import chat

    monkeypatch.setattr(llm_client, "_AUTO_INJECT", False)
    test_md_dir = tmp_path / "with_md"
    monkeypatch.setattr(flow_memory_md, "MEMORY_DIR", test_md_dir)
    user_md = test_md_dir / "user" / "u_disabled.md"
    user_md.parent.mkdir(parents=True, exist_ok=True)
    user_md.write_text("# 风格\n- 应该被忽略\n", encoding="utf-8")

    chat("hi", user_open_id="u_disabled")
    msgs = fake_openai["messages"]
    assert all("应该被忽略" not in (m.get("content") or "") for m in msgs)
