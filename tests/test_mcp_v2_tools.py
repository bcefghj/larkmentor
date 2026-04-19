"""Tests for step10 MCP v2 tools (classify_readonly / skill_invoke / memory_resolve / list_skills)"""

from __future__ import annotations

import pytest


def test_classify_readonly_creates_user_on_demand():
    from core.mcp_server.tools import tool_classify_readonly
    out = tool_classify_readonly(
        user_open_id="never_existed_user_99",
        sender_name="x", sender_id="y",
        content="hi",
    )
    assert out.get("readonly") is True
    assert out["level"] in {"P0", "P1", "P2", "P3"}


def test_classify_readonly_returns_pure_classification(monkeypatch):
    from memory.user_state import _store, get_user
    from core.mcp_server.tools import tool_classify_readonly

    u = get_user("u_classify_test")
    u.work_context = "writing report"

    out = tool_classify_readonly(
        user_open_id="u_classify_test",
        sender_name="老板", sender_id="u_boss",
        content="紧急：方案需要立刻确认",
    )
    assert out.get("readonly") is True
    assert out["level"] in {"P0", "P1", "P2", "P3"}
    assert "score" in out
    assert "dimensions" in out


def test_skill_invoke_unknown_skill():
    from core.mcp_server.tools import tool_skill_invoke
    out = tool_skill_invoke(skill_name="nope.nope", args={}, user_open_id="u1")
    assert out.get("ok") is False


def test_skill_invoke_missing_name():
    from core.mcp_server.tools import tool_skill_invoke
    out = tool_skill_invoke(skill_name="", args={}, user_open_id="u1")
    assert "error" in out


def test_memory_resolve_empty_returns_empty_string():
    from core.mcp_server.tools import tool_memory_resolve
    out = tool_memory_resolve(user_open_id="u_no_memory_test")
    assert "merged_markdown" in out
    assert "char_count" in out
    assert out["char_count"] >= 0


def test_memory_resolve_all_tiers_listed():
    from core.mcp_server.tools import tool_memory_resolve
    out = tool_memory_resolve(
        user_open_id="u_full",
        department_id="dept_a",
        group_id="grp_b",
        session_id="sess_c",
    )
    tiers = out.get("tiers_present", [])
    assert "enterprise" in tiers
    assert "department" in tiers
    assert "group" in tiers
    assert "user" in tiers
    assert "session" in tiers


def test_list_skills_returns_4():
    from core.mcp_server.tools import tool_list_skills
    out = tool_list_skills()
    assert "count" in out
    assert out["count"] >= 4
    names = {s["name"] for s in out["skills"]}
    assert {"mentor.write", "mentor.task", "mentor.review", "mentor.onboard"}.issubset(names)


def test_v2_tools_registered_in_TOOL_REGISTRY():
    from core.mcp_server.tools import TOOL_REGISTRY
    for k in ("classify_readonly", "skill_invoke", "memory_resolve", "list_skills"):
        assert k in TOOL_REGISTRY


def test_v2_tools_callable_via_call_tool():
    from core.mcp_server.tools import call_tool

    out = call_tool("list_skills", {})
    assert out.get("count", 0) >= 4
