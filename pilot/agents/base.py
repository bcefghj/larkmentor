"""Multi-Agent Pipeline 基础设施 — BaseAgent + AgentState + AgentLoop.

设计参考（竞品调研）:
  - Claude Code: async generator 状态机、错误恢复决策树、步骤预算、上下文压缩
  - Harness Engineering: 五层架构（Orchestration/Context/Tool/Verification/Operations）
  - CrewAI: 角色分工 + 结构化任务执行
  - GenSlide/SlideGen: Planner→Researcher→Writer→Reviewer→Builder 流水线
  - 行业标准: Circuit Breaker + Retry + Fallback + 幂等保护

所有 Agent 调 LLM 均走 `pilot.llm.client.default_client()`（MiniMax-M2.7-highspeed）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, TypedDict

logger = logging.getLogger("pilot.agents")


class AgentState(TypedDict, total=False):
    """Pipeline 共享状态（参考 LangGraph TypedDict 模式）。"""

    intent: str
    task_type: str
    outline: list
    research_results: list
    draft_sections: list
    review_feedback: str
    review_pass: bool
    artifacts: list
    iteration_count: int
    chat_id: str
    sender_open_id: str
    plan_id: str
    summary: str


class StopReason(Enum):
    """Agent Loop 终止原因（参考 Claude Code 的 continuation decision）。"""

    COMPLETED = "completed"
    MAX_STEPS = "max_steps"
    ERROR = "error"
    CONTEXT_OVERFLOW = "context_overflow"


# ---------------------------------------------------------------------------
# 错误恢复决策树（参考 Claude Code + Harness Engineering）
# ---------------------------------------------------------------------------

class ErrorRecovery:
    """Agent 执行错误的分类与恢复策略。

    参考:
      - Claude Code: prompt_too_long → autocompact; max_output → increase limit
      - Harness: 瞬态错误可重试, 确定性错误不重试
      - 行业标准: 3 次重试上限, 指数退避
    """

    MAX_RETRIES = 3

    @staticmethod
    def is_transient(error: Exception) -> bool:
        """判断是否为瞬态错误（可重试）。"""
        import httpx
        if isinstance(error, httpx.HTTPStatusError):
            code = error.response.status_code if error.response else 0
            return code == 429 or 500 <= code < 600
        if isinstance(error, (httpx.TimeoutException, httpx.TransportError)):
            return True
        if isinstance(error, asyncio.TimeoutError):
            return True
        return False

    @staticmethod
    def is_context_overflow(error: Exception) -> bool:
        """判断是否为上下文溢出。"""
        msg = str(error).lower()
        return any(kw in msg for kw in ("context length", "too long", "token limit", "max_tokens"))

    @staticmethod
    async def retry_with_backoff(coro_factory, *, max_retries: int = 3, base_delay: float = 1.0):
        """带指数退避的重试（参考 Claude Code retry logic）。"""
        import random
        last_exc = None
        for attempt in range(max_retries):
            try:
                return await coro_factory()
            except Exception as e:
                last_exc = e
                if not ErrorRecovery.is_transient(e):
                    raise
                delay = base_delay * (2 ** attempt) + random.random()
                logger.warning(
                    "Retry %d/%d after %.1fs: %s",
                    attempt + 1, max_retries, delay, e,
                )
                await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BaseAgent（增强版）
# ---------------------------------------------------------------------------

MAX_STEP_BUDGET = 30  # 参考 Harness: 20-50 步预算


class BaseAgent(ABC):
    """Agent 抽象基类（参考 Claude Code + Harness Engineering）。

    增强特性：
    - 步骤预算: 防止无限循环（Harness: 20-50 步）
    - 错误恢复: 瞬态错误自动重试、上下文溢出自动压缩
    - 执行计时: 记录每个 Agent 的耗时（Operations 层）
    """

    name: str = "base"
    role: str = ""
    system_prompt: str = ""
    max_retries: int = 3

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)
        self._step_count = 0
        self._start_time: float = 0

    @abstractmethod
    async def execute(self, state: AgentState) -> AgentState:
        """读取 state 中所需字段，执行逻辑，返回更新后的 state。"""
        ...

    async def safe_execute(self, state: AgentState) -> AgentState:
        """带错误恢复和计时的安全执行包装。

        参考 Claude Code 的错误恢复决策树:
        - 瞬态错误 → 重试（最多 3 次，指数退避）
        - 上下文溢出 → 压缩 prompt 后重试
        - 确定性错误 → 直接报错，不重试
        """
        self._start_time = time.time()
        self._step_count += 1

        if self._step_count > MAX_STEP_BUDGET:
            logger.error("%s exceeded step budget (%d)", self.name, MAX_STEP_BUDGET)
            return state

        try:
            result = await ErrorRecovery.retry_with_backoff(
                lambda: self.execute(state),
                max_retries=self.max_retries,
            )
            elapsed = time.time() - self._start_time
            logger.info(
                "%s completed in %.1fs (step %d)",
                self.name, elapsed, self._step_count,
            )
            return result
        except Exception as e:
            elapsed = time.time() - self._start_time
            if ErrorRecovery.is_context_overflow(e):
                logger.warning("%s context overflow, attempting compression: %s", self.name, e)
                state = self._compress_context(state)
                try:
                    return await self.execute(state)
                except Exception as e2:
                    logger.error("%s failed after compression: %s", self.name, e2)
                    return state
            logger.error("%s failed after %.1fs: %s", self.name, elapsed, e)
            return state

    def _compress_context(self, state: AgentState) -> AgentState:
        """上下文压缩策略（参考 Claude Code autocompact）。

        截断过长的 intent、research_results 等字段。
        """
        intent = state.get("intent", "")
        if len(intent) > 2000:
            state["intent"] = intent[:1500] + "\n...(已压缩)"

        research = state.get("research_results", [])
        if len(research) > 8:
            state["research_results"] = research[:6]

        draft = state.get("draft_sections", [])
        for section in draft:
            if isinstance(section, dict):
                content = section.get("content", "")
                if len(content) > 1000:
                    section["content"] = content[:800] + "\n...(已压缩)"

        return state

    async def _call_llm(
        self,
        user_prompt: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """调 MiniMax chat，返回 text 字段（带重试）。"""
        from pilot.llm.client import default_client

        async def _do():
            client = default_client()
            result = await client.chat(
                system=self.system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
            return result.get("text", "")

        return await ErrorRecovery.retry_with_backoff(_do, max_retries=self.max_retries)

    async def _call_llm_raw(
        self,
        user_prompt: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """调 MiniMax chat，返回完整 result dict（带重试）。"""
        from pilot.llm.client import default_client

        async def _do():
            client = default_client()
            return await client.chat(
                system=self.system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        return await ErrorRecovery.retry_with_backoff(_do, max_retries=self.max_retries)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} steps={self._step_count}>"
