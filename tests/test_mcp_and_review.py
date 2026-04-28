"""Unit tests for MCP tools + WorkReview."""

from __future__ import annotations

import time

import pytest

from core.flow_memory.archival import write_archival_summary, query_archival
from core.flow_memory.working import WorkingEvent, WorkingMemory
from core.mcp_server.tools import (
    TOOL_REGISTRY, call_tool, list_tools, tool_query_memory,
)
from core.work_review.weekly_report import generate_weekly_report
from core.work_review.monthly_wrapped import generate_monthly_wrapped


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    """Redirect the four data dirs to a tmp space so tests don't pollute."""
    import core.flow_memory.working as wm
    import core.flow_memory.archival as ar
    import core.security.audit_log as al

    monkeypatch.setattr(wm, "WM_DIR", tmp_path / "wm")
    (tmp_path / "wm").mkdir()

    monkeypatch.setattr(ar, "ARCHIVE_DIR", tmp_path / "ar")
    monkeypatch.setattr(ar, "ARCHIVE_FILE", tmp_path / "ar" / "summaries.jsonl")
    (tmp_path / "ar").mkdir()

    monkeypatch.setattr(al, "LOG_DIR", tmp_path / "audit")
    (tmp_path / "audit").mkdir()
    return tmp_path


# ── MCP tools ───────────────────────────────────────────────────────

def test_registry_lists_lark_mentor_tools():
    """LarkMentor keeps v3 six tools, adds four mentor_* tools, plus four coach_* aliases."""
    tools = list_tools()
    names = {t["name"] for t in tools}
    expected_v3 = {
        "get_focus_status", "classify_message", "get_recent_digest",
        "add_whitelist", "rollback_decision", "query_memory",
    }
    expected_mentor = {
        "mentor_review_message", "mentor_clarify_task",
        "mentor_draft_weekly", "mentor_search_org_kb",
    }
    expected_aliases = {
        "coach_review_message", "coach_clarify_task",
        "coach_draft_weekly", "coach_search_org_kb",
    }
    assert expected_v3.issubset(names), f"v3 tool missing: {expected_v3 - names}"
    assert expected_mentor.issubset(names), f"mentor tool missing: {expected_mentor - names}"
    assert expected_aliases.issubset(names), f"alias missing: {expected_aliases - names}"


def test_unknown_tool_returns_error():
    out = call_tool("does_not_exist", {})
    assert "error" in out


def test_query_memory_substring(isolated_data):
    write_archival_summary("ou_x", "本周做了 RAG 优化", kind="weekly")
    write_archival_summary("ou_x", "周二开了一个无关会议", kind="meeting")
    out = tool_query_memory("ou_x", "RAG", limit=5)
    assert isinstance(out, list)
    assert any("RAG" in (i.get("summary_md") or "") for i in out)


# ── Weekly report ───────────────────────────────────────────────────

def test_weekly_no_llm_fallback(isolated_data):
    wm = WorkingMemory(open_id="ou_weekly", capacity=20)
    now = int(time.time())
    wm.events.append(WorkingEvent(ts=now, kind="focus_start", payload={}))
    wm.events.append(WorkingEvent(ts=now + 1, kind="focus_end",
                                  payload={"duration_min": 25}))
    wm.events.append(WorkingEvent(ts=now + 2, kind="decision",
                                  payload={"level": "P0"}))
    wm.save()

    report = generate_weekly_report("ou_weekly", llm_chat=lambda p: "",
                                    publish=False)
    assert report.stats["focus_count"] == 1
    assert report.stats["focus_minutes"] == 25
    assert report.stats["p0"] == 1
    assert report.body_md  # non-empty


def test_weekly_with_llm(isolated_data):
    WorkingMemory(open_id="ou_w2", capacity=10).save()  # ensure file exists
    report = generate_weekly_report("ou_w2", llm_chat=lambda p: "## 本周\n\n做了很多事",
                                    publish=False)
    assert report.used_llm is True
    assert "本周" in report.body_md


# ── Monthly wrapped ─────────────────────────────────────────────────

def test_wrapped_returns_card(isolated_data):
    wm = WorkingMemory(open_id="ou_m", capacity=20)
    now = int(time.time())
    for _ in range(3):
        wm.events.append(WorkingEvent(ts=now, kind="focus_start", payload={}))
        wm.events.append(WorkingEvent(ts=now + 1, kind="focus_end",
                                      payload={"duration_min": 30}))
    wm.events.append(WorkingEvent(ts=now, kind="decision",
                                  payload={"level": "P0"}))
    wm.save()
    card = generate_monthly_wrapped("ou_m", days=30)
    assert card.stats["focus_starts"] == 3
    assert card.stats["focus_minutes"] == 90
    assert card.stats["p0"] == 1
    assert "过去" in card.headline
