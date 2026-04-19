"""Unit tests for v4 Mentor proactive hook (P0/P1 auto-suggest)."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from typing import List
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class FakeUser:
    open_id: str = "ou_test"
    rookie_mode: bool = True
    proactive_enabled: bool = True
    last_proactive_ts: int = 0
    proactive_log_24h: List[int] = field(default_factory=list)
    focus_mode: str = "deep"
    work_context: str = "review_pr"


@pytest.fixture
def hook(monkeypatch):
    from core.mentor import proactive_hook as ph

    # Stub LLM so tests never hit network.
    monkeypatch.setattr(
        "core.mentor.proactive_hook.chat_json",
        lambda *a, **k: {
            "three_versions": {
                "conservative": "收到，稍后回复",
                "neutral": "收到，今天给您反馈",
                "direct": "收到，方案 A/B 您选哪个？",
            },
            "risk_warning": "",
        },
    )
    # Stub KB to avoid sqlite + embedding.
    monkeypatch.setattr(
        "core.mentor.proactive_hook.kb.search",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "core.mentor.proactive_hook.kb.render_citations",
        lambda hits: "（无组织文档）",
    )
    yield ph


def test_fires_for_p0(hook):
    u = FakeUser()
    decision = hook.maybe_suggest(
        u, sender_name="老板", sender_role="leader",
        chat_name="项目群", message="紧急：方案有问题需要立刻确认",
        level="P0",
    )
    assert decision.fired is True
    assert decision.suggestion["three_versions"]["conservative"]


def test_skips_for_p2(hook):
    u = FakeUser()
    decision = hook.maybe_suggest(
        u, sender_name="同事", sender_role="peer",
        chat_name="闲聊", message="今天午饭吃啥",
        level="P2",
    )
    assert decision.fired is False
    assert decision.reason == "level_P2"


def test_blocked_when_user_disabled(hook):
    u = FakeUser(proactive_enabled=False)
    decision = hook.maybe_suggest(
        u, sender_name="老板", sender_role="leader",
        chat_name="x", message="紧急", level="P0",
    )
    assert decision.fired is False
    assert decision.reason == "user_disabled"


def test_blocked_when_rookie_mode_off(hook):
    u = FakeUser(rookie_mode=False)
    decision = hook.maybe_suggest(
        u, sender_name="老板", sender_role="leader",
        chat_name="x", message="紧急", level="P0",
    )
    assert decision.fired is False
    assert decision.reason == "rookie_mode_off"


def test_cooldown_blocks_within_5min(hook):
    u = FakeUser(last_proactive_ts=int(time.time()) - 60)  # 1 minute ago
    decision = hook.maybe_suggest(
        u, sender_name="老板", sender_role="leader",
        chat_name="x", message="紧急", level="P0",
    )
    assert decision.fired is False
    assert "cooldown" in decision.reason


def test_cooldown_passes_after_5min(hook):
    u = FakeUser(last_proactive_ts=int(time.time()) - 600)  # 10 min ago
    decision = hook.maybe_suggest(
        u, sender_name="老板", sender_role="leader",
        chat_name="x", message="紧急", level="P0",
    )
    assert decision.fired is True


def test_24h_cap(hook):
    now = int(time.time())
    # Already 3 fires within last 24h
    u = FakeUser(proactive_log_24h=[now - 7200, now - 3600, now - 1800])
    decision = hook.maybe_suggest(
        u, sender_name="老板", sender_role="leader",
        chat_name="x", message="紧急", level="P0",
    )
    assert decision.fired is False
    assert "daily_cap" in decision.reason


def test_mark_fired_updates_state(hook):
    u = FakeUser()
    hook.mark_fired(u)
    assert u.last_proactive_ts > 0
    assert len(u.proactive_log_24h) == 1
