"""Unit tests for FlowMemory three layers + flow_memory.md resolver."""

from __future__ import annotations

import time

import pytest

from core.flow_memory.compaction import compact_session, micro_compact, session_compact
from core.flow_memory.flow_memory_md import resolve_memory_md, write_tier
from core.flow_memory.working import WorkingEvent, WorkingMemory


def _make_event(kind="message", offset=0):
    return WorkingEvent(ts=int(time.time()) + offset, kind=kind, payload={"x": offset})


def test_working_append_and_save_roundtrip(tmp_path, monkeypatch):
    import core.flow_memory.working as wm_mod
    monkeypatch.setattr(wm_mod, "WM_DIR", tmp_path)
    wm = WorkingMemory(open_id="ou_test", capacity=10)
    for i in range(5):
        wm.append(_make_event(offset=i))
    wm.save()
    again = WorkingMemory.load("ou_test")
    assert len(again.events) == 5


def test_working_overflow_spills(tmp_path, monkeypatch):
    import core.flow_memory.working as wm_mod
    monkeypatch.setattr(wm_mod, "WM_DIR", tmp_path)
    wm = WorkingMemory(open_id="ou_t2", capacity=8)
    spilled = None
    for i in range(20):
        out = wm.append(_make_event(offset=i))
        if out is not None:
            spilled = out
    assert spilled is not None
    assert len(wm.events) <= 8


def test_micro_compact_counts_kinds():
    events = [_make_event("message", i) for i in range(10)] + \
             [_make_event("decision", i) for i in range(3)]
    res = micro_compact(events)
    assert res.event_count == 13
    assert "message" in res.summary_md
    assert "decision" in res.summary_md
    assert res.used_llm is False


def test_session_compact_uses_injected_llm():
    events = [_make_event("message", i) for i in range(40)]
    res = session_compact(events, llm_chat=lambda p: "LLM SAYS HI")
    assert res.summary_md == "LLM SAYS HI"
    assert res.used_llm is True


def test_compact_auto_routes_by_size():
    small = [_make_event("message", i) for i in range(5)]
    big = [_make_event("message", i) for i in range(50)]
    r1 = compact_session(small, tier="auto", llm_chat=lambda p: "LLM")
    r2 = compact_session(big, tier="auto", llm_chat=lambda p: "LLM")
    assert r1.used_llm is False  # micro path
    assert r2.used_llm is True   # session path


def test_flow_memory_md_resolver(tmp_path, monkeypatch):
    import core.flow_memory.flow_memory_md as md_mod
    monkeypatch.setattr(md_mod, "MEMORY_DIR", tmp_path)
    write_tier("user", "ou_demo", "## 我的偏好\n\n上级=老板A")
    write_tier("workspace", "default", "## 工作区规则\n\n禁止发广告")
    out = resolve_memory_md(workspace_id="default", user_open_id="ou_demo")
    assert "我的偏好" in out
    assert "工作区规则" in out
    assert out.index("Workspace") < out.index("User")  # higher tier first


def test_flow_memory_md_resolver_empty(tmp_path, monkeypatch):
    import core.flow_memory.flow_memory_md as md_mod
    monkeypatch.setattr(md_mod, "MEMORY_DIR", tmp_path)
    out = resolve_memory_md()
    assert out == ""
