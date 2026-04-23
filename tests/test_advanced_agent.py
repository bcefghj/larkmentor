"""Tests for Agent-Pilot's "advanced Agent" behaviours (good-to-have)."""

from __future__ import annotations

import pytest

from core.agent_pilot.advanced import (
    diagnose_intent,
    summarise_messages,
    recommend_next_steps,
)
from core.agent_pilot.planner import PilotPlanner


def test_diagnose_flags_very_short_intent_as_ambiguous():
    d = diagnose_intent("做个方案")
    assert d.should_clarify
    assert d.ambiguity > 0.5
    assert d.questions
    assert len(d.questions) <= 3


def test_diagnose_does_not_flag_concrete_intent():
    d = diagnose_intent(
        "今天下午 5 点前，给上级写一份产品评审 PPT，覆盖架构与时间线"
    )
    # This intent names audience, when, scope → ambiguity should drop.
    # We allow either "not clarify" or empty questions list.
    assert d.ambiguity <= 0.65


def test_planner_prepends_clarify_step_for_ambiguous_intents():
    planner = PilotPlanner(chat_json_fn=lambda *a, **k: {})
    plan = planner.plan("帮我处理")
    # First step should be mentor.clarify
    assert plan.steps[0].tool == "mentor.clarify"
    assert plan.steps[0].args.get("questions")
    # Subsequent original steps must depend on the clarify step
    clarify_id = plan.steps[0].step_id
    downstream_depending_on_clarify = [
        s for s in plan.steps[1:] if clarify_id in s.depends_on
    ]
    assert len(downstream_depending_on_clarify) >= 1


def test_planner_skips_clarify_when_disabled():
    planner = PilotPlanner(chat_json_fn=lambda *a, **k: {})
    plan = planner.plan("模糊指令", allow_clarify=False)
    assert plan.steps[0].tool != "mentor.clarify"


def test_summarise_empty_messages_returns_empty():
    assert summarise_messages([]) == ""


def test_summarise_without_llm_returns_deterministic_fallback(monkeypatch):
    # Force chat() to fail so we exercise the fallback path
    import llm.llm_client as lc
    monkeypatch.setattr(lc, "chat", lambda *a, **k: "")
    out = summarise_messages([
        {"sender": "戴尚好", "text": "我们要做 Agent-Pilot 产品"},
        {"sender": "李洁盈", "text": "优先级是多端同步"},
    ])
    assert out
    assert "共识" in out or "初步" in out


def test_recommend_next_steps_uses_tool_profile():
    plan = {
        "steps": [
            {"tool": "doc.create"},
            {"tool": "slide.generate"},
            {"tool": "archive.bundle"},
        ]
    }
    recs = recommend_next_steps(plan)
    assert any("评审会议" in r for r in recs)
    assert any("上级" in r or "评委" in r for r in recs)
    assert len(recs) <= 3
