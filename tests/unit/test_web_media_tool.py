"""V1.5 — web.search / media.tts 工具注册与执行回归."""

from __future__ import annotations

import os

import pytest

from pilot.capability.tools.registry import default_registry


@pytest.mark.asyncio
async def test_web_search_registered() -> None:
    reg = default_registry()
    spec = reg.get("web.search")
    assert spec is not None
    assert "query" in spec.input_schema["properties"]


@pytest.mark.asyncio
async def test_web_search_execute_with_mocked_searcher(monkeypatch) -> None:
    from pilot.llm import web_search as ws

    async def fake_search(self, query, *, k=5):
        return [
            {"title": "A", "url": "https://a.com", "snippet": "a"},
            {"title": "B", "url": "https://b.com", "snippet": "b"},
        ]

    monkeypatch.setattr(ws.WebSearcher, "search", fake_search)

    reg = default_registry()
    res = await reg.execute(tool_name="web.search", tool_input={"query": "AI", "k": 2}, ctx={})
    assert res["ok"] is True
    assert res["count"] == 2
    assert res["results"][0]["url"] == "https://a.com"


@pytest.mark.asyncio
async def test_media_tts_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_PILOT_ENABLE_TTS", raising=False)
    reg = default_registry()
    res = await reg.execute(tool_name="media.tts", tool_input={"text": "hi"}, ctx={})
    assert res["ok"] is False
    assert res["reason"] == "tts_disabled"


@pytest.mark.asyncio
async def test_media_tts_missing_credentials(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_PILOT_ENABLE_TTS", "1")
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_GROUP_ID", raising=False)
    reg = default_registry()
    res = await reg.execute(tool_name="media.tts", tool_input={"text": "hi"}, ctx={})
    assert res["ok"] is False
    assert "credentials" in res["reason"]
