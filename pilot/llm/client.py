"""LLM 客户端 — 多 Provider 抽象层.

支持:
  - Anthropic (Claude)
  - OpenAI / 兼容（豆包 / 自部署）
  - MiniMax
  - Mock（测试用）

设计原则:
  - chat_stream / chat 均为 async
  - 工具调用统一为 OpenAI tool_use 格式
  - 429 / quota 错误自动指数退避（tenacity）
  - 单一接口 LLMClient，全局单例 default_client()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx

logger = logging.getLogger("pilot.llm.client")


# ── 数据 ───────────────────────────────────────────────────────────────────


@dataclass
class LLMResponse:
    """统一返回结构（含 Anthropic content list 与 OpenAI 格式兼容字段）."""

    content: list[dict[str, Any]]  # [{"type": "text", "text": "..."}, {"type": "tool_use", ...}]
    text: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    raw: dict[str, Any] | None = None
    tokens_in: int = 0
    tokens_out: int = 0


# ── 客户端实现 ──────────────────────────────────────────────────────────────


class LLMClient:
    """统一 LLM 接口."""

    def __init__(
        self,
        *,
        provider: str = "",
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        timeout: float = 120.0,
    ) -> None:
        self.provider = provider or os.getenv("LLM_DEFAULT_PROVIDER", "anthropic").lower()
        self.api_key = api_key or self._guess_api_key()
        self.base_url = base_url or self._guess_base_url()
        self.model = model or self._guess_model()
        self.timeout = timeout
        self._http: httpx.AsyncClient | None = None

    def _guess_api_key(self) -> str:
        if self.provider == "anthropic":
            return os.getenv("ANTHROPIC_API_KEY", "")
        if self.provider == "minimax":
            return os.getenv("MINIMAX_API_KEY", "")
        if self.provider == "doubao":
            return os.getenv("DOUBAO_API_KEY", "")
        return os.getenv("LLM_API_KEY", "")

    def _guess_base_url(self) -> str:
        if self.provider == "anthropic":
            return os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        if self.provider == "doubao":
            return os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
        if self.provider == "minimax":
            return "https://api.minimax.chat"
        return ""

    def _guess_model(self) -> str:
        if self.provider == "anthropic":
            return os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
        if self.provider == "minimax":
            return os.getenv("MINIMAX_MODEL", "MiniMax-Text-01")
        if self.provider == "doubao":
            return os.getenv("DOUBAO_MODEL", "doubao-1-5-pro-32k-250115")
        return ""

    async def _http_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.timeout)
        return self._http

    # ── chat (non-stream) ──
    async def chat(
        self,
        *,
        system: str = "",
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
        provider_override: str = "",
    ) -> dict[str, Any]:
        """统一 chat 接口，返回 dict（含 content list）."""
        provider = (provider_override or self.provider).lower()

        if not self.api_key:
            return await self._mock_chat(system=system, messages=messages or [], tools=tools or [])

        for attempt in range(3):
            try:
                if provider == "anthropic":
                    return await self._chat_anthropic(system, messages or [], tools, temperature, max_tokens)
                if provider == "minimax":
                    return await self._chat_minimax(system, messages or [], tools, temperature, max_tokens)
                if provider == "doubao":
                    return await self._chat_openai_compat(
                        base_url=self.base_url,
                        api_key=self.api_key,
                        model=self.model,
                        system=system,
                        messages=messages or [],
                        tools=tools,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                # 默认 OpenAI 兼容
                return await self._chat_openai_compat(
                    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                    api_key=self.api_key,
                    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    system=system,
                    messages=messages or [],
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except httpx.HTTPStatusError as e:
                code = e.response.status_code if e.response else 0
                if code == 429 or 500 <= code < 600:
                    sleep = (2 ** attempt) + random.random()
                    logger.warning("LLM %s status=%d; retry in %.1fs", provider, code, sleep)
                    await asyncio.sleep(sleep)
                    continue
                logger.error("LLM %s status=%d body=%s", provider, code, e.response.text[:200])
                raise
            except Exception as e:
                logger.warning("LLM %s attempt %d failed: %s", provider, attempt + 1, e)
                if attempt < 2:
                    await asyncio.sleep((2 ** attempt) + random.random())
                else:
                    raise

        raise RuntimeError("LLM chat failed after 3 retries")

    async def chat_stream(
        self,
        *,
        system: str = "",
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.5,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式接口（占位实现：拆 chat 为单 chunk）.

        生产中应直接调用 Anthropic / OpenAI 的 SSE，这里先用非流式包装。
        """
        result = await self.chat(
            system=system,
            messages=messages,
            tools=tools,
            temperature=temperature,
        )
        for block in result.get("content", []):
            yield block

    # ── Anthropic ──
    async def _chat_anthropic(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self.model,
            "system": system,
            "messages": _to_anthropic_messages(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = _to_anthropic_tools(tools)

        client = await self._http_client()
        r = await client.post(url, json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
        usage = data.get("usage", {}) or {}
        return {
            "content": data.get("content", []),
            "tokens_in": usage.get("input_tokens", 0),
            "tokens_out": usage.get("output_tokens", 0),
            "raw": data,
        }

    # ── OpenAI 兼容 ──
    async def _chat_openai_compat(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        msgs = [{"role": "system", "content": system}] + _to_openai_messages(messages)
        body: dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = _to_openai_tools(tools)

        client = await self._http_client()
        r = await client.post(url, json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message", {}) or {}
        text = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []

        content_blocks: list[dict[str, Any]] = []
        if text:
            content_blocks.append({"type": "text", "text": text})
        for tc in tool_calls:
            fn = tc.get("function", {})
            try:
                inp = json.loads(fn.get("arguments", "{}"))
            except Exception:
                inp = {"_raw": fn.get("arguments", "")}
            content_blocks.append({
                "type": "tool_use",
                "id": tc.get("id", ""),
                "name": fn.get("name", ""),
                "input": inp,
            })

        usage = data.get("usage", {}) or {}
        return {
            "content": content_blocks,
            "text": text,
            "tool_calls": tool_calls,
            "tokens_in": usage.get("prompt_tokens", 0),
            "tokens_out": usage.get("completion_tokens", 0),
            "raw": data,
        }

    # ── MiniMax ──
    async def _chat_minimax(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        # MiniMax v2 兼容 OpenAI Chat 格式
        return await self._chat_openai_compat(
            base_url=f"{self.base_url}/v1",
            api_key=self.api_key,
            model=self.model,
            system=system,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # ── Mock（无 key 时回退）──
    async def _mock_chat(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                last_user = m["content"]
                break

        # 如果工具集中有 doc.create 等，模拟一次工具调用
        if tools:
            tool_name = tools[0].get("name", "doc.create")
            return {
                "content": [
                    {"type": "text", "text": f"[mock] 收到意图：{last_user[:60]}，将调用 {tool_name}"},
                    {
                        "type": "tool_use",
                        "id": f"toolu_mock_{int(time.time())}",
                        "name": tool_name,
                        "input": {"title": last_user[:30] or "[Agent-Pilot] mock"},
                    },
                ],
                "tokens_in": 100,
                "tokens_out": 50,
                "raw": {"_mock": True},
            }

        return {
            "content": [
                {"type": "text", "text": f"[mock] 你说: {last_user[:80]}（这是 LLM 兜底回复，请配置 API key）"},
            ],
            "tokens_in": 50,
            "tokens_out": 20,
            "raw": {"_mock": True},
        }

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None


# ── 辅助：消息 / 工具格式转换 ───────────────────────────────────────────────


def _to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI/通用消息 → Anthropic content list."""
    out = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            continue  # Anthropic 用顶层 system
        if isinstance(content, str):
            out.append({"role": role, "content": [{"type": "text", "text": content}]})
        else:
            out.append({"role": role, "content": content})
    return out


def _to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for m in messages:
        role = m.get("role", "user")
        if role == "tool":
            out.append({
                "role": "tool",
                "tool_call_id": m.get("tool_use_id", ""),
                "content": json.dumps(m.get("content", "")) if not isinstance(m.get("content"), str) else m.get("content"),
            })
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return out


def _to_anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tools:
        out.append({
            "name": t.get("name", ""),
            "description": t.get("description", ""),
            "input_schema": t.get("input_schema", {"type": "object", "properties": {}}),
        })
    return out


def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tools:
        out.append({
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return out


# ── 全局单例 ──


_default: LLMClient | None = None


def default_client() -> LLMClient:
    global _default
    if _default is None:
        _default = LLMClient()
    return _default


def get_client(provider: str = "") -> LLMClient:
    if not provider:
        return default_client()
    return LLMClient(provider=provider)
