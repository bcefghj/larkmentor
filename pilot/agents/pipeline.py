"""Pipeline 编排 — doc_pipeline / ppt_pipeline / trio_pipeline.

参考 CrewAI 的顺序流水线模式，每个 pipeline 串联多个 Agent，
共享 AgentState，逐步充实内容直到产出最终产物。

核心流程:
  Planner → Research → Writer → Review(循环 max 3 次) → Builder

ReviewAgent 不通过时，将 feedback 注入 state 让 Writer 重写，最多循环 3 次。
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from pilot.agents.base import AgentState
from pilot.agents.builder import BuilderAgent
from pilot.agents.intent import IntentAgent
from pilot.agents.planner import PlannerAgent
from pilot.agents.researcher import ResearchAgent
from pilot.agents.reviewer import ReviewAgent
from pilot.agents.writer import WriterAgent

logger = logging.getLogger("pilot.agents.pipeline")

MAX_REVIEW_ITERATIONS = 3


def _get_event_log(state: AgentState):
    """获取 EventLog 实例（用于 Dashboard 实时展示 Agent 协作过程）."""
    try:
        from pilot.context.event_log import EventLog
        plan_id = state.get("plan_id", "")
        return EventLog(session_id=plan_id) if plan_id else None
    except Exception:
        return None


async def _emit(event_log, kind: str, payload: dict) -> None:
    """向 EventLog 写入事件（Dashboard SSE 实时推送）."""
    if event_log is None:
        return
    try:
        await event_log.append(kind, payload)
    except Exception as e:
        logger.debug("EventLog emit failed: %s", e)


async def doc_pipeline(state: AgentState) -> AgentState:
    """文档 pipeline: Planner → Research → Writer → Review(循环) → Builder.

    state 必须预填 intent / chat_id / sender_open_id。
    每步都 emit EventLog 事件，Dashboard SSE 可实时展示 Agent 协作过程。
    """
    state["task_type"] = state.get("task_type") or "doc"
    state["plan_id"] = state.get("plan_id") or f"plan_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    state["iteration_count"] = 0

    planner = PlannerAgent()
    researcher = ResearchAgent()
    writer = WriterAgent()
    reviewer = ReviewAgent()
    builder = BuilderAgent()

    event_log = _get_event_log(state)

    logger.info("[doc_pipeline] start: intent=%s", state.get("intent", "")[:60])

    # 聚合上下文记忆
    try:
        from pilot.context.context_pack import ContextPackBuilder  # noqa: F401
        from pilot.context.event_log import EventLog

        recent_sessions = EventLog.list_sessions(limit=5)
        history_context = []
        for sid in recent_sessions[:3]:
            log = EventLog(session_id=sid)
            events = await log.read_recent(limit=5)
            if events:
                summary = f"历史任务 {sid[:16]}: " + str(events[0].get("payload", {}).get("intent", ""))[:60]
                history_context.append(summary)

        if history_context:
            state["intent"] = state.get("intent", "") + "\n\n[上下文参考]\n" + "\n".join(history_context)
    except Exception as e:
        logger.debug("ContextPack aggregation skipped: %s", e)

    await _emit(event_log, "agent.start", {"agent": "PlannerAgent", "role": "任务规划", "step": "生成结构化大纲"})

    state = await planner.execute(state)
    await _emit(event_log, "agent.done", {"agent": "PlannerAgent", "sections": len(state.get("outline", []))})
    logger.info("[doc_pipeline] planner done: %d sections", len(state.get("outline", [])))

    await _emit(event_log, "agent.start", {"agent": "ResearchAgent", "role": "联网搜索", "step": "为每章搜索支撑数据"})
    state = await researcher.execute(state)
    await _emit(event_log, "agent.done", {"agent": "ResearchAgent", "findings": sum(len(r.get("findings", [])) for r in state.get("research_results", []))})
    logger.info("[doc_pipeline] researcher done: %d results", len(state.get("research_results", [])))

    for iteration in range(MAX_REVIEW_ITERATIONS):
        state["iteration_count"] = iteration + 1

        await _emit(event_log, "agent.start", {"agent": "WriterAgent", "role": "内容撰写", "step": f"第 {iteration+1} 轮撰写", "iteration": iteration + 1})
        state = await writer.execute(state)
        await _emit(event_log, "agent.done", {"agent": "WriterAgent", "sections_written": len(state.get("draft_sections", []))})
        logger.info("[doc_pipeline] writer iteration %d: %d sections", iteration + 1, len(state.get("draft_sections", [])))

        await _emit(event_log, "agent.start", {"agent": "ReviewAgent", "role": "质量审核", "step": f"第 {iteration+1} 轮自评"})
        state = await reviewer.execute(state)
        await _emit(event_log, "agent.done", {"agent": "ReviewAgent", "pass": state.get("review_pass"), "feedback": state.get("review_feedback", "")[:100]})
        logger.info("[doc_pipeline] reviewer iteration %d: pass=%s", iteration + 1, state.get("review_pass"))

        if state.get("review_pass"):
            break

        if iteration < MAX_REVIEW_ITERATIONS - 1:
            await _emit(event_log, "agent.revise", {"agent": "ReviewAgent", "reason": state.get("review_feedback", "")[:200]})
            _inject_feedback(state)

    await _emit(event_log, "agent.start", {"agent": "BuilderAgent", "role": "组装交付", "step": "写入飞书文档"})
    state = await builder.execute(state)
    await _emit(event_log, "agent.done", {"agent": "BuilderAgent", "artifacts": len(state.get("artifacts", []))})
    logger.info("[doc_pipeline] builder done: %d artifacts", len(state.get("artifacts", [])))

    return state


async def ppt_pipeline(state: AgentState) -> AgentState:
    """PPT pipeline: Planner → Research → Writer → Review → Builder(python-pptx)."""
    state["task_type"] = "ppt"
    state["plan_id"] = state.get("plan_id") or f"plan_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    state["iteration_count"] = 0

    planner = PlannerAgent()
    researcher = ResearchAgent()
    writer = WriterAgent()
    reviewer = ReviewAgent()
    builder = BuilderAgent()

    logger.info("[ppt_pipeline] start: intent=%s", state.get("intent", "")[:60])

    state = await planner.execute(state)
    state = await researcher.execute(state)

    for iteration in range(MAX_REVIEW_ITERATIONS):
        state["iteration_count"] = iteration + 1
        state = await writer.execute(state)
        state = await reviewer.execute(state)

        if state.get("review_pass"):
            break
        if iteration < MAX_REVIEW_ITERATIONS - 1:
            _inject_feedback(state)

    state = await builder.execute(state)
    logger.info("[ppt_pipeline] done: %d artifacts", len(state.get("artifacts", [])))
    return state


async def trio_pipeline(state: AgentState) -> AgentState:
    """三件套 pipeline: doc + ppt + archive.

    复用 doc_pipeline 的内容生成结果，再调 BuilderAgent 生成 PPT 和归档。
    """
    state["task_type"] = "trio"
    state["plan_id"] = state.get("plan_id") or f"plan_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    state["iteration_count"] = 0

    planner = PlannerAgent()
    researcher = ResearchAgent()
    writer = WriterAgent()
    reviewer = ReviewAgent()
    builder = BuilderAgent()

    logger.info("[trio_pipeline] start: intent=%s", state.get("intent", "")[:60])

    state = await planner.execute(state)
    state = await researcher.execute(state)

    for iteration in range(MAX_REVIEW_ITERATIONS):
        state["iteration_count"] = iteration + 1
        state = await writer.execute(state)
        state = await reviewer.execute(state)

        if state.get("review_pass"):
            break
        if iteration < MAX_REVIEW_ITERATIONS - 1:
            _inject_feedback(state)

    state = await builder.execute(state)

    logger.info("[trio_pipeline] done: %d artifacts", len(state.get("artifacts", [])))
    return state


async def run_pipeline(state: AgentState) -> AgentState:
    """根据 state["task_type"] 自动选择 pipeline 并执行。

    完整流程：IntentAgent → 选择 pipeline → 执行。
    """
    intent_agent = IntentAgent()
    state = await intent_agent.execute(state)

    verdict = state.get("_verdict", "task")  # type: ignore[typeddict-item]
    if verdict == "chat":
        state["artifacts"] = [{"type": "chat_reply", "text": "我在哦～需要帮你做点什么？"}]
        return state
    if verdict == "clarify":
        state["artifacts"] = [{"type": "clarify", "text": "能再详细描述一下你的需求吗？"}]
        return state

    task_type = state.get("task_type", "doc")
    if task_type == "ppt":
        return await ppt_pipeline(state)
    elif task_type == "trio":
        return await trio_pipeline(state)
    else:
        return await doc_pipeline(state)


def _inject_feedback(state: AgentState) -> None:
    """将审核反馈注入 state，供 Writer 下轮参考。"""
    feedback = state.get("review_feedback", "")
    if not feedback:
        return

    existing_intent = state.get("intent", "")
    state["intent"] = (
        f"{existing_intent}\n\n"
        f"[审核反馈 - 第{state.get('iteration_count', 0)}轮] {feedback}\n"
        f"请根据反馈修改以下章节内容。"
    )
