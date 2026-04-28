"""P15 · 6-tier Memory 真正注入到 Pilot system prompt 的测试."""
from __future__ import annotations

import os

import pytest

from core.agent_pilot.application import (
    ContextBuildOptions,
    ContextService,
    attach_memory_to_default_services,
    make_memory_resolver_adapter,
    wrap_llm_with_memory,
)


def test_memory_resolver_adapter_returns_callable():
    fn = make_memory_resolver_adapter()
    assert callable(fn)
    # 没有 markdown 文件时返回空串，不抛异常
    assert fn(tenant="default", workspace="default") == ""


def test_memory_resolver_adapter_reads_markdown(tmp_path, monkeypatch):
    """写入临时 enterprise.md，resolver 应能读到内容."""
    # 临时切换 MEMORY_DIR
    import core.flow_memory.flow_memory_md as fm
    backup = fm.MEMORY_DIR
    fm.MEMORY_DIR = tmp_path
    try:
        ent = tmp_path / "enterprise"
        ent.mkdir()
        (ent / "default.md").write_text("# 我司财年是 4-3 月\n\nCEO 是张总。", encoding="utf-8")
        fn = make_memory_resolver_adapter()
        md = fn(tenant="default", workspace="default")
        assert "财年" in md
    finally:
        fm.MEMORY_DIR = backup


def test_wrap_llm_with_memory_prepends_context(tmp_path):
    captured = {}

    def fake_llm(text):
        captured["seen"] = text
        return '{"is_task": false}'

    import core.flow_memory.flow_memory_md as fm
    backup = fm.MEMORY_DIR
    fm.MEMORY_DIR = tmp_path
    try:
        ent = tmp_path / "enterprise"
        ent.mkdir()
        (ent / "T1.md").write_text("我司主营校园活动", encoding="utf-8")
        wrapped = wrap_llm_with_memory(fake_llm, tenant="T1", workspace="default")
        wrapped("用户消息")
        assert "memory_context" in captured["seen"]
        assert "校园活动" in captured["seen"]
        assert "用户消息" in captured["seen"]
    finally:
        fm.MEMORY_DIR = backup


def test_wrap_llm_no_memory_passes_through(tmp_path):
    """没有任何 markdown 文件时，wrapper 直接转发原 prompt."""
    captured = {}

    def fake_llm(text):
        captured["seen"] = text
        return "ok"

    import core.flow_memory.flow_memory_md as fm
    backup = fm.MEMORY_DIR
    fm.MEMORY_DIR = tmp_path  # empty
    try:
        wrapped = wrap_llm_with_memory(fake_llm)
        wrapped("用户消息")
        assert captured["seen"] == "用户消息"
        assert "memory_context" not in captured["seen"]
    finally:
        fm.MEMORY_DIR = backup


def test_context_service_uses_resolver(tmp_path):
    """ContextService.resolve_memory_md 调用注入的 resolver."""
    import core.flow_memory.flow_memory_md as fm
    backup = fm.MEMORY_DIR
    fm.MEMORY_DIR = tmp_path
    try:
        wsp = tmp_path / "workspace"
        wsp.mkdir()
        (wsp / "marketing.md").write_text("营销组每周五汇报", encoding="utf-8")
        svc = ContextService(memory_resolver=make_memory_resolver_adapter(),
                              upload_root=str(tmp_path / "u"))
        opts = ContextBuildOptions(
            task_id="t1", task_goal="x", owner_open_id="u1",
            workspace_id="marketing",
        )
        md = svc.resolve_memory_md(opts)
        assert "每周五" in md
    finally:
        fm.MEMORY_DIR = backup


def test_attach_memory_to_default_binds_resolver(tmp_path):
    """attach_memory_to_default_services 把 default_context_service 的 resolver 设上."""
    import core.flow_memory.flow_memory_md as fm
    from core.agent_pilot.application.context_service import default_context_service

    backup = fm.MEMORY_DIR
    fm.MEMORY_DIR = tmp_path
    try:
        # reset default service so binding is fresh
        import core.agent_pilot.application.context_service as csm
        csm._default_service = None

        attach_memory_to_default_services()
        ctx = default_context_service()
        assert ctx.memory_resolver is not None

        ent = tmp_path / "enterprise"
        ent.mkdir()
        (ent / "default.md").write_text("我司核心业务", encoding="utf-8")

        opts = ContextBuildOptions(
            task_id="t1", task_goal="x", owner_open_id="u1",
        )
        md = ctx.resolve_memory_md(opts)
        assert "核心业务" in md
    finally:
        fm.MEMORY_DIR = backup
        # cleanup default service
        import core.agent_pilot.application.context_service as csm
        csm._default_service = None


def test_six_tiers_merge_low_overrides_high(tmp_path):
    """6 级合并：低层应该出现在合并 markdown 的下方."""
    import core.flow_memory.flow_memory_md as fm
    backup = fm.MEMORY_DIR
    fm.MEMORY_DIR = tmp_path
    try:
        for tier, ident, body in [
            ("enterprise", "T1", "## ENT_LINE"),
            ("workspace", "W1", "## WSP_LINE"),
            ("user", "U1", "## USER_LINE"),
            ("session", "S1", "## SESSION_LINE"),
        ]:
            d = tmp_path / tier
            d.mkdir()
            (d / f"{ident}.md").write_text(body, encoding="utf-8")
        fn = make_memory_resolver_adapter()
        md = fn(tenant="T1", workspace="W1", user="U1", session="S1")
        # all four sections present
        for tag in ("ENT_LINE", "WSP_LINE", "USER_LINE", "SESSION_LINE"):
            assert tag in md
        # session 应在最后（lower override higher）
        idx = {tag: md.find(tag) for tag in ("ENT_LINE", "WSP_LINE", "USER_LINE", "SESSION_LINE")}
        assert idx["ENT_LINE"] < idx["WSP_LINE"] < idx["USER_LINE"] < idx["SESSION_LINE"]
    finally:
        fm.MEMORY_DIR = backup
