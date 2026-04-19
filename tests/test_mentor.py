"""Unit tests for v4 Mentor: router + writing + task + weekly + cards.

We mock out LLM and KB so tests are fast and deterministic.
"""

from __future__ import annotations

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Mentor Router (5 cases) ────────────────────────────────────────────────

def test_router_keyword_short_circuit_writing(monkeypatch):
    from core.mentor.mentor_router import route

    # No LLM should be called for keyword hits.
    called = {"llm": False}

    def _llm(*a, **k):
        called["llm"] = True
        return {}

    monkeypatch.setattr("core.mentor.mentor_router.chat_json", _llm)
    d = route("帮我看看这条消息怎么改")
    assert d.role == "writing"
    assert d.method == "keyword"
    assert called["llm"] is False


def test_router_keyword_weekly():
    from core.mentor.mentor_router import route

    d = route("写一下本周周报")
    assert d.role == "weekly"
    assert d.method == "keyword"


def test_router_keyword_task():
    from core.mentor.mentor_router import route

    d = route("收到一个新需求要拆解")
    assert d.role == "task"


def test_router_falls_back_to_llm(monkeypatch):
    from core.mentor.mentor_router import route

    monkeypatch.setattr(
        "core.mentor.mentor_router.chat_json",
        lambda *a, **k: {"role": "task", "confidence": 0.7, "why": "ambiguous"},
    )
    d = route("你看这个事情应该怎么办")  # no keyword match
    assert d.role == "task"
    assert d.method == "llm"


def test_router_empty_input_is_chitchat():
    from core.mentor.mentor_router import route

    d = route("")
    assert d.role == "chitchat"


# ── Writing mentor (10 cases) ──────────────────────────────────────────────

@pytest.fixture
def stub_kb_empty(monkeypatch):
    monkeypatch.setattr("core.mentor.mentor_write.kb.search", lambda *a, **k: [])
    monkeypatch.setattr(
        "core.mentor.mentor_write.kb.render_citations",
        lambda hits: "（无组织文档）",
    )


def test_writing_review_returns_three_versions(monkeypatch, stub_kb_empty):
    from core.mentor.mentor_write import review

    monkeypatch.setattr(
        "core.mentor.mentor_write.chat_json",
        lambda *a, **k: {
            "risk_level": "medium",
            "risk_description": "略显推责",
            "nvc_diagnosis": {
                "observation": "原文",
                "feeling": "焦虑",
                "need": "确认",
                "request": "请尽快回复",
            },
            "three_versions": {
                "conservative": "收到，稍后回复",
                "neutral": "收到，今天给您反馈",
                "direct": "收到，方案 A 选哪个？",
            },
            "explanation": "更直接",
            "uses_org_style": False,
        },
    )
    r = review("ou_test", "你为什么还没回复我")
    assert r.risk_level == "medium"
    assert r.three_versions["conservative"]
    assert r.three_versions["neutral"]
    assert r.three_versions["direct"]
    assert r.fallback is False


def test_writing_review_empty_message():
    from core.mentor.mentor_write import review

    r = review("ou_test", "")
    assert r.risk_level == "low"
    assert "无需改写" in r.explanation


def test_writing_review_llm_fail_falls_back(monkeypatch, stub_kb_empty):
    from core.mentor.mentor_write import review

    monkeypatch.setattr("core.mentor.mentor_write.chat_json", lambda *a, **k: {})
    r = review("ou_test", "随便写一段话")
    assert r.fallback is True
    assert r.three_versions["conservative"]


def test_writing_review_to_dict_serialisable(monkeypatch, stub_kb_empty):
    from core.mentor.mentor_write import review

    monkeypatch.setattr("core.mentor.mentor_write.chat_json", lambda *a, **k: {})
    d = review("ou_test", "x").to_dict()
    assert "three_versions" in d
    assert "nvc_diagnosis" in d
    assert "fallback" in d


def test_writing_review_with_citations(monkeypatch):
    from core.mentor import mentor_write
    from core.mentor.knowledge_base import Chunk, SearchHit

    chunk = Chunk(id=1, open_id="ou_x", source="rules.md", chunk_idx=0, text="规则", ts=0)
    hit = SearchHit(chunk=chunk, score=0.9, method="embedding")
    monkeypatch.setattr(mentor_write.kb, "search", lambda *a, **k: [hit])
    monkeypatch.setattr(
        mentor_write.kb, "render_citations", lambda hits: "[来源: rules.md #0]\n规则",
    )
    monkeypatch.setattr(
        mentor_write, "chat_json",
        lambda *a, **k: {
            "risk_level": "low",
            "three_versions": {"conservative": "a", "neutral": "b", "direct": "c"},
            "uses_org_style": True,
        },
    )
    r = mentor_write.review("ou_x", "请帮我润色")
    assert r.uses_org_style is True
    assert r.citations == ["[来源: rules.md #0]"]


def test_writing_review_invalid_risk_defaults_low(monkeypatch, stub_kb_empty):
    from core.mentor.mentor_write import review

    monkeypatch.setattr(
        "core.mentor.mentor_write.chat_json",
        lambda *a, **k: {
            "three_versions": {"conservative": "a", "neutral": "b", "direct": "c"},
        },
    )
    r = review("ou_test", "msg")
    assert r.risk_level == "low"


def test_writing_review_preserves_message_in_direct_fallback(monkeypatch, stub_kb_empty):
    from core.mentor.mentor_write import review

    monkeypatch.setattr("core.mentor.mentor_write.chat_json", lambda *a, **k: {})
    msg = "下午 3 点开会"
    r = review("ou_test", msg)
    assert r.three_versions["direct"] == msg


def test_writing_review_recipient_passed(monkeypatch, stub_kb_empty):
    """Sanity: the recipient hint reaches the prompt formatter."""
    from core.mentor.mentor_write import review

    captured = {}

    def _capture_chat_json(prompt, **kw):
        captured["prompt"] = prompt
        return {"three_versions": {"conservative": "a", "neutral": "b", "direct": "c"}}

    monkeypatch.setattr("core.mentor.mentor_write.chat_json", _capture_chat_json)
    review("ou_test", "msg", recipient="项目经理")
    assert "项目经理" in captured["prompt"]


def test_writing_review_strips_long_message(monkeypatch, stub_kb_empty):
    from core.mentor.mentor_write import review

    long_msg = "a" * 10000
    monkeypatch.setattr("core.mentor.mentor_write.chat_json", lambda *a, **k: {})
    r = review("ou_test", long_msg)
    assert isinstance(r.three_versions, dict)


def test_writing_review_truncates_nvc_fields(monkeypatch, stub_kb_empty):
    """Bad LLM output (overly long NVC fields) should still produce a card."""
    from core.mentor.mentor_write import review

    monkeypatch.setattr(
        "core.mentor.mentor_write.chat_json",
        lambda *a, **k: {
            "nvc_diagnosis": {
                "observation": "x" * 1000,
                "feeling": "", "need": "", "request": "",
            },
            "three_versions": {"conservative": "a", "neutral": "b", "direct": "c"},
        },
    )
    r = review("ou_test", "msg")
    assert isinstance(r.nvc_diagnosis, dict)
    assert r.nvc_diagnosis["observation"]


# ── Task mentor (8 cases) ──────────────────────────────────────────────────

@pytest.fixture
def stub_kb_for_task(monkeypatch):
    monkeypatch.setattr("core.mentor.mentor_task.kb.search", lambda *a, **k: [])
    monkeypatch.setattr(
        "core.mentor.mentor_task.kb.render_citations",
        lambda hits: "（无组织文档）",
    )


def test_task_clarify_high_ambiguity(monkeypatch, stub_kb_for_task):
    from core.mentor.mentor_task import clarify

    monkeypatch.setattr(
        "core.mentor.mentor_task.chat_json",
        lambda *a, **k: {
            "ambiguity": 0.8,
            "missing_dims": ["scope", "deadline"],
            "suggested_questions": ["范围是什么？", "什么时候交？"],
            "ready_to_start": False,
        },
    )
    r = clarify("ou_x", "搞一下那个事")
    assert r.needs_clarification is True
    assert len(r.suggested_questions) == 2


def test_task_clarify_low_ambiguity(monkeypatch, stub_kb_for_task):
    from core.mentor.mentor_task import clarify

    monkeypatch.setattr(
        "core.mentor.mentor_task.chat_json",
        lambda *a, **k: {
            "ambiguity": 0.2,
            "missing_dims": [],
            "task_understanding": "做一个 10 页 PPT 介绍 v4",
            "delivery_plan": "1. 大纲 2. 写稿 3. 审阅",
            "risks": ["时间紧"],
            "ready_to_start": True,
        },
    )
    r = clarify("ou_x", "做一个介绍 v4 的 10 页 PPT，周五交")
    assert r.needs_clarification is False
    assert r.delivery_plan
    assert r.ready_to_start is True


def test_task_clarify_filters_invalid_dims(monkeypatch, stub_kb_for_task):
    from core.mentor.mentor_task import clarify

    monkeypatch.setattr(
        "core.mentor.mentor_task.chat_json",
        lambda *a, **k: {
            "ambiguity": 0.6,
            "missing_dims": ["scope", "fake_dim", "deadline", "garbage"],
            "suggested_questions": ["q1"],
        },
    )
    r = clarify("ou_x", "x")
    assert "fake_dim" not in r.missing_dims
    assert "garbage" not in r.missing_dims


def test_task_clarify_caps_questions_to_two(monkeypatch, stub_kb_for_task):
    from core.mentor.mentor_task import clarify

    monkeypatch.setattr(
        "core.mentor.mentor_task.chat_json",
        lambda *a, **k: {
            "ambiguity": 0.9,
            "suggested_questions": ["q1", "q2", "q3", "q4", "q5"],
        },
    )
    r = clarify("ou_x", "x")
    assert len(r.suggested_questions) == 2


def test_task_clarify_clamps_ambiguity(monkeypatch, stub_kb_for_task):
    from core.mentor.mentor_task import clarify

    monkeypatch.setattr(
        "core.mentor.mentor_task.chat_json",
        lambda *a, **k: {"ambiguity": 99.0, "suggested_questions": ["q"]},
    )
    r = clarify("ou_x", "x")
    assert 0.0 <= r.ambiguity <= 1.0


def test_task_clarify_empty_input(stub_kb_for_task):
    from core.mentor.mentor_task import clarify

    r = clarify("ou_x", "")
    assert r.ambiguity == 1.0
    assert r.suggested_questions


def test_task_clarify_llm_fail_fallback(monkeypatch, stub_kb_for_task):
    from core.mentor.mentor_task import clarify

    monkeypatch.setattr("core.mentor.mentor_task.chat_json", lambda *a, **k: {})
    r = clarify("ou_x", "搞一下")
    assert r.fallback is True
    assert r.suggested_questions


def test_task_clarify_to_dict_includes_needs_flag(monkeypatch, stub_kb_for_task):
    from core.mentor.mentor_task import clarify

    monkeypatch.setattr(
        "core.mentor.mentor_task.chat_json",
        lambda *a, **k: {"ambiguity": 0.7, "suggested_questions": ["q"]},
    )
    d = clarify("ou_x", "x").to_dict()
    assert d["needs_clarification"] is True


# ── Weekly mentor (7 cases) ────────────────────────────────────────────────

@pytest.fixture
def stub_weekly_deps(monkeypatch):
    monkeypatch.setattr(
        "core.mentor.mentor_review.kb.search", lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "core.mentor.mentor_review.kb.render_citations", lambda hits: "（无组织文档）",
    )


def test_weekly_draft_with_llm(monkeypatch, stub_weekly_deps):
    from core.mentor.mentor_review import draft

    star_body = "## 本周完成\n- [S] 项目 [T] 优化 [A] 重构 [R] 性能+30% [来源: archival_1]"
    monkeypatch.setattr("core.mentor.mentor_review.chat", lambda *a, **k: star_body)
    wk = draft("ou_x")
    assert wk.used_llm is True
    assert wk.used_star is True
    assert "[S]" in wk.body_md


def test_weekly_draft_llm_fail_fallback(monkeypatch, stub_weekly_deps):
    from core.mentor.mentor_review import draft

    monkeypatch.setattr("core.mentor.mentor_review.chat", lambda *a, **k: "")
    wk = draft("ou_x")
    assert wk.used_llm is False
    assert "[S]" in wk.body_md  # fallback also has STAR


def test_weekly_draft_returns_stats(monkeypatch, stub_weekly_deps):
    from core.mentor.mentor_review import draft

    monkeypatch.setattr("core.mentor.mentor_review.chat", lambda *a, **k: "## body")
    wk = draft("ou_x")
    assert "focus_count" in wk.stats
    assert "p0" in wk.stats


def test_weekly_draft_used_star_detection(monkeypatch, stub_weekly_deps):
    from core.mentor.mentor_review import draft

    monkeypatch.setattr(
        "core.mentor.mentor_review.chat", lambda *a, **k: "no markers here",
    )
    wk = draft("ou_x")
    assert wk.used_star is False


def test_weekly_to_dict_keys(monkeypatch, stub_weekly_deps):
    from core.mentor.mentor_review import draft

    monkeypatch.setattr("core.mentor.mentor_review.chat", lambda *a, **k: "")
    d = draft("ou_x").to_dict()
    for key in ("body_md", "stats", "citations", "used_llm", "used_star"):
        assert key in d


def test_weekly_draft_week_offset(monkeypatch, stub_weekly_deps):
    from core.mentor.mentor_review import draft

    monkeypatch.setattr("core.mentor.mentor_review.chat", lambda *a, **k: "")
    wk0 = draft("ou_x", week_offset=0)
    wk1 = draft("ou_x", week_offset=1)
    assert wk0.week_start_ts > wk1.week_start_ts


def test_weekly_draft_user_meta_passed(monkeypatch, stub_weekly_deps):
    from core.mentor.mentor_review import draft

    captured = {}
    monkeypatch.setattr(
        "core.mentor.mentor_review.chat",
        lambda prompt, **kw: (captured.setdefault("prompt", prompt), "")[1],
    )
    draft("ou_x", user_meta="李洁盈/产品/首周")
    assert "李洁盈" in captured["prompt"]
