"""LLM 客户端 — V1.5 起锁定 MiniMax-M2.7-highspeed.

设计取舍（V1 → V1.5 的批判性收敛）:
  - V1 时期挂了 anthropic / doubao / openai_compat 三套分支，实际只对 MiniMax 做过线上验证，
    其他分支等同死代码 → 移除。
  - 仅保留 MiniMax 的 OpenAI 兼容 endpoint（/v1/chat/completions），不再写多 provider 抽象层。
  - 通过 `LLM_MOCK=1` 或缺失 `MINIMAX_API_KEY` 触发 mock，保证测试与离线环境可跑。
  - 重试预算：429/5xx 指数退避，最多 3 次，整体 budget 30s。

公开 API 与 V1 保持兼容，外部调用点仅依赖 `default_client().chat(...)`。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger("pilot.llm.client")

DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_MODEL = "MiniMax-M2.7-highspeed"
RETRY_BUDGET_SEC = 30.0
RETRY_MAX_ATTEMPTS = 3

# Circuit Breaker 参数（参考行业标准: 3-5 次失败阈值, 5 分钟窗口）
CB_FAILURE_THRESHOLD = 5
CB_RECOVERY_TIMEOUT = 300.0  # 5 minutes
CB_HALF_OPEN_MAX = 2


class CircuitBreaker:
    """LLM API Circuit Breaker（参考 Harness Engineering + 行业标准）。

    状态机: CLOSED → OPEN → HALF_OPEN → CLOSED
    - CLOSED: 正常运行，记录失败次数
    - OPEN: 拒绝请求，等待恢复超时
    - HALF_OPEN: 允许少量请求试探恢复
    """

    def __init__(self) -> None:
        self._failures = 0
        self._state = "closed"  # closed / open / half_open
        self._last_failure_time = 0.0
        self._half_open_attempts = 0

    @property
    def is_open(self) -> bool:
        if self._state == "open":
            if time.time() - self._last_failure_time > CB_RECOVERY_TIMEOUT:
                self._state = "half_open"
                self._half_open_attempts = 0
                logger.info("CircuitBreaker: OPEN → HALF_OPEN (recovery timeout reached)")
                return False
            return True
        return False

    def record_success(self) -> None:
        if self._state == "half_open":
            self._state = "closed"
            self._failures = 0
            logger.info("CircuitBreaker: HALF_OPEN → CLOSED (success)")
        elif self._state == "closed":
            self._failures = max(0, self._failures - 1)

    def record_failure(self) -> None:
        self._failures += 1
        self._last_failure_time = time.time()
        if self._state == "half_open":
            self._half_open_attempts += 1
            if self._half_open_attempts >= CB_HALF_OPEN_MAX:
                self._state = "open"
                logger.warning("CircuitBreaker: HALF_OPEN → OPEN (too many failures)")
        elif self._state == "closed" and self._failures >= CB_FAILURE_THRESHOLD:
            self._state = "open"
            logger.warning("CircuitBreaker: CLOSED → OPEN (%d failures)", self._failures)


_circuit_breaker = CircuitBreaker()


@dataclass
class LLMResponse:
    """统一返回结构（保留 OpenAI / Anthropic 风格的 content list 兼容字段）."""

    content: list[dict[str, Any]]
    text: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    raw: dict[str, Any] | None = None
    tokens_in: int = 0
    tokens_out: int = 0


class LLMClient:
    """MiniMax-M2.7-highspeed 客户端（OpenAI 兼容协议）."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY", "")
        self.base_url = (base_url or os.getenv("MINIMAX_API_HOST", DEFAULT_BASE_URL)).rstrip("/")
        if not self.base_url.endswith("/v1"):
            self.base_url = f"{self.base_url}/v1"
        self.model = model or os.getenv("MINIMAX_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self.provider = "minimax"  # 兼容历史代码读取 .provider
        self._http: httpx.AsyncClient | None = None

    async def _http_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.timeout)
        return self._http

    @property
    def is_mock(self) -> bool:
        if os.getenv("LLM_MOCK", "").lower() in ("1", "true", "yes"):
            return True
        return not self.api_key

    async def chat(
        self,
        *,
        system: str = "",
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
        provider_override: str = "",
    ) -> dict[str, Any]:
        """统一 chat 接口（含 Circuit Breaker 保护）。"""
        if provider_override and provider_override.lower() != "minimax":
            logger.debug("provider_override=%s ignored (V1.5 MiniMax-only)", provider_override)

        if self.is_mock:
            return await self._mock_chat(system=system, messages=messages or [], tools=tools or [])

        if _circuit_breaker.is_open:
            logger.warning("CircuitBreaker OPEN: returning graceful degradation response")
            return {
                "content": [{"type": "text", "text": "(服务暂时不可用，请稍后重试)"}],
                "text": "(服务暂时不可用，请稍后重试)",
                "tool_calls": [],
                "tokens_in": 0,
                "tokens_out": 0,
                "raw": {"_circuit_breaker": "open"},
            }

        deadline = time.monotonic() + RETRY_BUDGET_SEC
        last_exc: Exception | None = None
        for attempt in range(RETRY_MAX_ATTEMPTS):
            if time.monotonic() > deadline:
                break
            try:
                result = await self._chat_minimax(
                    system=system,
                    messages=messages or [],
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                )
                _circuit_breaker.record_success()
                return result
            except httpx.HTTPStatusError as e:
                code = e.response.status_code if e.response is not None else 0
                last_exc = e
                _circuit_breaker.record_failure()
                if code == 429 or 500 <= code < 600:
                    sleep = min(2 ** attempt + random.random(), max(0.0, deadline - time.monotonic()))
                    logger.warning("MiniMax %d retry %d/%d in %.1fs", code, attempt + 1, RETRY_MAX_ATTEMPTS, sleep)
                    if sleep <= 0:
                        break
                    await asyncio.sleep(sleep)
                    continue
                body_preview = e.response.text[:200] if e.response is not None else ""
                logger.error("MiniMax fatal status=%d body=%s", code, body_preview)
                raise
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_exc = e
                _circuit_breaker.record_failure()
                sleep = min(2 ** attempt + random.random(), max(0.0, deadline - time.monotonic()))
                logger.warning("MiniMax network attempt %d failed: %s; retry in %.1fs", attempt + 1, e, sleep)
                if sleep <= 0:
                    break
                await asyncio.sleep(sleep)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("MiniMax chat exhausted retry budget")

    async def chat_stream(
        self,
        *,
        system: str = "",
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.5,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式接口（占位实现：拆 chat 为单 chunk）."""
        result = await self.chat(
            system=system,
            messages=messages,
            tools=tools,
            temperature=temperature,
        )
        for block in result.get("content", []):
            yield block

    async def _chat_minimax(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        msgs: list[dict[str, Any]] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(_to_openai_messages(messages))

        body: dict[str, Any] = {
            "model": self.model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = _to_openai_tools(tools)
        if response_format:
            body["response_format"] = response_format

        client = await self._http_client()
        r = await client.post(url, json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
        return _parse_openai_response(data)

    async def _mock_chat(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        last_user = ""
        for m in reversed(messages):
            content = m.get("content", "")
            if m.get("role") == "user" and isinstance(content, str):
                last_user = content
                break

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
                "text": f"[mock] {last_user[:60]}",
                "tool_calls": [],
                "tokens_in": 100,
                "tokens_out": 50,
                "raw": {"_mock": True},
            }

        text = f"[mock] 你说: {last_user[:80]}（请配置 MINIMAX_API_KEY 走真实 LLM）"
        return {
            "content": [{"type": "text", "text": text}],
            "text": text,
            "tool_calls": [],
            "tokens_in": 50,
            "tokens_out": 20,
            "raw": {"_mock": True},
        }

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None


def _to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """通用消息 → OpenAI/MiniMax 兼容消息."""
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role", "user")
        if role == "tool":
            content = m.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            out.append({
                "role": "tool",
                "tool_call_id": m.get("tool_use_id", "") or m.get("tool_call_id", ""),
                "content": content,
            })
            continue

        content = m.get("content", "")
        if isinstance(content, list):
            joined: list[str] = []
            for blk in content:
                if isinstance(blk, dict):
                    if blk.get("type") == "text":
                        joined.append(blk.get("text", ""))
                    elif blk.get("type") == "tool_use":
                        joined.append(f"[tool_use {blk.get('name', '')} {json.dumps(blk.get('input', {}), ensure_ascii=False)}]")
                else:
                    joined.append(str(blk))
            content = "\n".join(t for t in joined if t)
        out.append({"role": role, "content": content})
    return out


def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """统一工具 schema → OpenAI 函数调用格式."""
    out: list[dict[str, Any]] = []
    for t in tools:
        if "function" in t and "type" in t:
            out.append(t)
            continue
        out.append({
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return out


def _strip_thinking(text: str) -> tuple[str, str]:
    """移除 MiniMax M2.7 的内部标记，保留纯净回复文本。

    处理两类标记：
    1. <think>...</think> — 推理过程标签
    2. [TOOL_CALL]...[/TOOL_CALL] — MiniMax 联网搜索内部工具调用标记

    Returns:
        (clean_text, thinking_content)
    """
    m = re.search(r'<think>([\s\S]*?)</think>', text)
    thinking = m.group(1).strip() if m else ""
    stripped = re.sub(r'<think>[\s\S]*?</think>\s*', '', text)
    stripped = re.sub(r'\[TOOL_CALL\][\s\S]*?\[/TOOL_CALL\]\s*', '', stripped)
    stripped = re.sub(r'\[/?TOOL_CALL\]', '', stripped)
    return stripped.strip(), thinking


def _parse_openai_response(data: dict[str, Any]) -> dict[str, Any]:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message", {}) or {}
    raw_text = message.get("content") or ""
    tool_calls = message.get("tool_calls") or []

    text, thinking = _strip_thinking(raw_text) if raw_text else ("", "")

    blocks: list[dict[str, Any]] = []
    if text:
        blocks.append({"type": "text", "text": text})
    for tc in tool_calls:
        fn = tc.get("function", {}) or {}
        try:
            inp = json.loads(fn.get("arguments", "{}"))
        except Exception:
            inp = {"_raw": fn.get("arguments", "")}
        blocks.append({
            "type": "tool_use",
            "id": tc.get("id", ""),
            "name": fn.get("name", ""),
            "input": inp,
        })

    usage = data.get("usage", {}) or {}
    raw = dict(data)
    if thinking:
        raw["thinking"] = thinking
    return {
        "content": blocks,
        "text": text,
        "tool_calls": tool_calls,
        "tokens_in": usage.get("prompt_tokens", 0),
        "tokens_out": usage.get("completion_tokens", 0),
        "raw": raw,
    }


_default: LLMClient | None = None


def default_client() -> LLMClient:
    global _default
    if _default is None:
        _default = LLMClient()
    return _default


def get_client(provider: str = "") -> LLMClient:
    """保留签名兼容历史调用；V1.5 起强制返回 MiniMax 单例."""
    if provider and provider.lower() != "minimax":
        logger.debug("get_client(provider=%s) ignored (V1.5 MiniMax-only)", provider)
    return default_client()
