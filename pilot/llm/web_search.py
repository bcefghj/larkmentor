"""免费联网搜索 — DuckDuckGo HTML 主路径 + Bing CN 兜底.

为什么不叫 minimax_mcp？
  - 实现是 HTTP 抓 HTML，不是 MCP 协议、也不依赖 MiniMax 服务，命名要诚实。
  - MiniMax 提供的 minimax-search MCP 在 stdio 子进程里管理麻烦（systemd 不友好），
    且 HTTP 直抓即可满足 Planner 的"联网注入最新数据"需求。

接口：
  - WebSearcher.search(query, k=5) -> list[{title,url,snippet}]
  - default_searcher() 返回单例
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

logger = logging.getLogger("pilot.llm.web_search")

DDG_ENDPOINT = "https://html.duckduckgo.com/html/"
BING_CN_ENDPOINT = "https://cn.bing.com/search"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


class WebSearcher:
    """HTTP 抓取式联网搜索器（无 API key 依赖）."""

    def __init__(self, *, timeout: float = 12.0) -> None:
        self.timeout = timeout
        self._http: httpx.AsyncClient | None = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def search(self, query: str, *, k: int = 5) -> list[dict[str, str]]:
        """先 DDG 后 Bing；都失败返回空 list。绝不抛异常给上游."""
        q = (query or "").strip()
        if not q:
            return []

        try:
            results = await self._search_ddg(q, k=k)
            if results:
                return results
        except Exception as e:
            logger.warning("DDG search failed: %s", e)

        try:
            return await self._search_bing(q, k=k)
        except Exception as e:
            logger.warning("Bing CN search failed: %s", e)
            return []

    async def _search_ddg(self, query: str, *, k: int) -> list[dict[str, str]]:
        client = await self._client()
        r = await client.post(
            DDG_ENDPOINT,
            data={"q": query},
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        r.raise_for_status()
        return parse_ddg_html(r.text, k=k)

    async def _search_bing(self, query: str, *, k: int) -> list[dict[str, str]]:
        client = await self._client()
        r = await client.get(
            BING_CN_ENDPOINT,
            params={"q": query, "ensearch": 0},
            headers={"User-Agent": USER_AGENT},
        )
        r.raise_for_status()
        return parse_bing_html(r.text, k=k)


_DDG_RESULT_RE = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL,
)


def parse_ddg_html(html: str, *, k: int = 5) -> list[dict[str, str]]:
    """从 DuckDuckGo HTML SERP 提取前 k 条结果."""
    out: list[dict[str, str]] = []
    for m in _DDG_RESULT_RE.finditer(html):
        url = _unwrap_ddg(m.group("url"))
        title = _strip_html(m.group("title"))
        snippet = _strip_html(m.group("snippet"))
        if not url or not title:
            continue
        out.append({"title": title[:200], "url": url[:500], "snippet": snippet[:400]})
        if len(out) >= k:
            break
    return out


def _unwrap_ddg(href: str) -> str:
    """DDG 用 //duckduckgo.com/l/?uddg=https%3A... 跳转，剥出真实 URL."""
    if href.startswith("//"):
        href = "https:" + href
    if "duckduckgo.com/l/" in href:
        try:
            qs = parse_qs(urlparse(href).query)
            return unquote(qs.get("uddg", [href])[0])
        except Exception:
            return href
    return href


_BING_RESULT_RE = re.compile(
    r'<li[^>]*class="b_algo"[^>]*>.*?'
    r'<h2[^>]*>.*?<a[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?</h2>.*?'
    r'<p[^>]*>(?P<snippet>.*?)</p>',
    re.DOTALL,
)


def parse_bing_html(html: str, *, k: int = 5) -> list[dict[str, str]]:
    """从 Bing CN HTML SERP 提取前 k 条结果."""
    out: list[dict[str, str]] = []
    for m in _BING_RESULT_RE.finditer(html):
        url = m.group("url").strip()
        title = _strip_html(m.group("title"))
        snippet = _strip_html(m.group("snippet"))
        if not url or not title:
            continue
        out.append({"title": title[:200], "url": url[:500], "snippet": snippet[:400]})
        if len(out) >= k:
            break
    return out


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


_default: WebSearcher | None = None


def default_searcher() -> WebSearcher:
    global _default
    if _default is None:
        _default = WebSearcher()
    return _default
