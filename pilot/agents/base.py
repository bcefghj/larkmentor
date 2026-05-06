"""Multi-Agent Pipeline 基础设施 — BaseAgent 抽象类 + AgentState.

设计参考:
  - LangGraph TypedDict state 模式：pipeline 中所有 agent 共享一个 state dict，
    每个 agent 读取所需字段、写入产出字段，编排层串联。
  - CrewAI Agent 角色分工：每个 agent 有 name / role / system_prompt。
  - GenSlide Agentic Builder：Planner→Researcher→Writer→Reviewer→Builder 流水线。

所有 Agent 调 LLM 均走 `pilot.llm.client.default_client()`（MiniMax-M2.7-highspeed）。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, TypedDict

logger = logging.getLogger("pilot.agents")


class AgentState(TypedDict, total=False):
    """Pipeline 共享状态，参考 LangGraph 的 TypedDict 设计。"""

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


class BaseAgent(ABC):
    """Agent 抽象基类。

    子类必须实现 ``execute``；可复用 ``_call_llm`` 调 MiniMax。
    """

    name: str = "base"
    role: str = ""
    system_prompt: str = ""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)

    @abstractmethod
    async def execute(self, state: AgentState) -> AgentState:
        """读取 state 中所需字段，执行逻辑，返回更新后的 state。"""
        ...

    async def _call_llm(
        self,
        user_prompt: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """调 MiniMax chat，返回 text 字段。"""
        from pilot.llm.client import default_client

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

    async def _call_llm_raw(
        self,
        user_prompt: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """调 MiniMax chat，返回完整 result dict（含 tool_calls 等）。"""
        from pilot.llm.client import default_client

        client = default_client()
        return await client.chat(
            system=self.system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
