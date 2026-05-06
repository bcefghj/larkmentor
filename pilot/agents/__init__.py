"""pilot.agents — Multi-Agent Pipeline 架构.

参考 GenSlide / CrewAI 的设计：
  - 每个 Agent 有独立 role + system_prompt
  - 共享 AgentState（TypedDict），pipeline 编排层串联
  - 流水线：Planner → Researcher → Writer → Reviewer → Builder

用法::

    from pilot.agents import run_pipeline, AgentState

    state: AgentState = {
        "intent": "帮我写一份 AI 行业分析报告",
        "chat_id": "oc_xxx",
        "sender_open_id": "ou_xxx",
    }
    result = await run_pipeline(state)
    print(result["artifacts"])
"""

from pilot.agents.base import AgentState, BaseAgent
from pilot.agents.builder import BuilderAgent
from pilot.agents.intent import IntentAgent
from pilot.agents.pipeline import (
    doc_pipeline,
    ppt_pipeline,
    run_pipeline,
    trio_pipeline,
)
from pilot.agents.planner import PlannerAgent
from pilot.agents.researcher import ResearchAgent
from pilot.agents.reviewer import ReviewAgent
from pilot.agents.writer import WriterAgent

__all__ = [
    "AgentState",
    "BaseAgent",
    "IntentAgent",
    "PlannerAgent",
    "ResearchAgent",
    "WriterAgent",
    "ReviewAgent",
    "BuilderAgent",
    "doc_pipeline",
    "ppt_pipeline",
    "trio_pipeline",
    "run_pipeline",
]
