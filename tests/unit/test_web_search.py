"""V1.5 — web_search HTML 解析回归（不依赖网络）."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from pilot.llm import web_search


DDG_FIXTURE = """
<html><body>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">第一个 <b>标题</b></a>
  <a class="result__snippet" href="x">这是 <em>第一个</em> 摘要片段。</a>
</div>
<div class="result">
  <a class="result__a" href="https://example.com/b">Title B</a>
  <a class="result__snippet" href="x">Snippet B</a>
</div>
</body></html>
"""


BING_FIXTURE = """
<html><body>
<li class="b_algo">
  <h2><a href="https://news.example.com/x">News X</a></h2>
  <p>News X 摘要。</p>
</li>
<li class="b_algo">
  <h2><a href="https://blog.example.com/y">Blog Y</a></h2>
  <p>Blog Y snippet</p>
</li>
</body></html>
"""


def test_parse_ddg_html_extracts_top_k() -> None:
    res = web_search.parse_ddg_html(DDG_FIXTURE, k=5)
    assert len(res) == 2
    assert res[0]["url"] == "https://example.com/a"
    assert "第一个" in res[0]["title"]
    assert res[0]["snippet"].startswith("这是")
    assert res[1]["url"] == "https://example.com/b"


def test_parse_bing_html_extracts_top_k() -> None:
    res = web_search.parse_bing_html(BING_FIXTURE, k=5)
    assert len(res) == 2
    assert res[0]["title"] == "News X"
    assert res[0]["url"] == "https://news.example.com/x"


def test_parse_ddg_respects_k_limit() -> None:
    res = web_search.parse_ddg_html(DDG_FIXTURE, k=1)
    assert len(res) == 1


def test_searcher_falls_back_to_bing_when_ddg_fails() -> None:
    async def fake_get(self, *args, **kwargs):
        request = httpx.Request("GET", BING_CN := "https://cn.bing.com/search")
        return httpx.Response(200, text=BING_FIXTURE, request=request)

    async def fake_post(self, *args, **kwargs):
        raise httpx.TimeoutException("ddg down")

    async def run() -> None:
        searcher = web_search.WebSearcher(timeout=1.0)
        with patch.object(httpx.AsyncClient, "post", new=fake_post), patch.object(
            httpx.AsyncClient, "get", new=fake_get
        ):
            results = await searcher.search("test query", k=2)
        assert results, "fallback should produce results"
        assert results[0]["title"] == "News X"
        await searcher.aclose()

    asyncio.run(run())


def test_searcher_returns_empty_when_both_fail() -> None:
    async def boom_post(self, *args, **kwargs):
        raise httpx.TimeoutException("ddg down")

    async def boom_get(self, *args, **kwargs):
        raise httpx.TimeoutException("bing down")

    async def run() -> None:
        searcher = web_search.WebSearcher(timeout=1.0)
        with patch.object(httpx.AsyncClient, "post", new=boom_post), patch.object(
            httpx.AsyncClient, "get", new=boom_get
        ):
            results = await searcher.search("test query")
        assert results == []
        await searcher.aclose()

    asyncio.run(run())


def test_searcher_empty_query_short_circuits() -> None:
    async def run() -> None:
        searcher = web_search.WebSearcher()
        assert await searcher.search("") == []
        assert await searcher.search("   ") == []

    asyncio.run(run())
