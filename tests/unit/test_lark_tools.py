"""V1.5 — lark.* 工具注册 + 缺凭据降级回归."""

from __future__ import annotations

import pytest

from pilot.capability.tools.registry import default_registry


@pytest.mark.asyncio
async def test_lark_tools_registered() -> None:
    reg = default_registry()
    for name in ("lark.im.fetch_thread", "lark.doc.search", "lark.bitable.search"):
        spec = reg.get(name)
        assert spec is not None, name
        assert spec.namespace == "lark"


@pytest.mark.asyncio
async def test_lark_im_fetch_thread_no_credentials(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_your_app_id_here")
    reg = default_registry()
    res = await reg.execute(tool_name="lark.im.fetch_thread", tool_input={"chat_id": "oc_xxx"}, ctx={})
    assert res["ok"] is False
    assert res["reason"] == "no_feishu_credentials"


@pytest.mark.asyncio
async def test_lark_doc_search_no_credentials(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_your_app_id_here")
    reg = default_registry()
    res = await reg.execute(tool_name="lark.doc.search", tool_input={"query": "PRD"}, ctx={})
    assert res["ok"] is False
    assert res["reason"] == "no_feishu_credentials"


@pytest.mark.asyncio
async def test_lark_bitable_search_missing_table_id(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_real_app_id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "real_secret")
    reg = default_registry()
    res = await reg.execute(tool_name="lark.bitable.search", tool_input={}, ctx={})
    assert res["ok"] is False
    assert res["reason"] == "missing_table_id"


@pytest.mark.asyncio
async def test_lark_doc_search_empty_query(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_real")
    monkeypatch.setenv("FEISHU_APP_SECRET", "real_secret")
    reg = default_registry()
    res = await reg.execute(tool_name="lark.doc.search", tool_input={"query": ""}, ctx={})
    assert res["ok"] is False
    assert res["reason"] == "empty_query"
