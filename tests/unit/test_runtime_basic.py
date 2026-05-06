"""测试 Runtime 层基础：Session/Task/Step + IntentRouter + Planner + Orchestrator."""

from __future__ import annotations

import asyncio
import pytest

from pilot.runtime.session import Session, SessionMode, Step, StepKind, StepStatus, Task, TaskState
from pilot.runtime.intent_router import (
    ChatMessage,
    IntentRouter,
    IntentVerdict,
    LLMJudgement,
)
from pilot.runtime.planner import Plan, plan_from_intent
from pilot.runtime.orchestrator import Orchestrator


# ── Session/Task ─────────────────────────────────────────────────────────────


def test_session_create():
    s = Session(user_open_id="ou_xxx", chat_id="oc_yyy")
    assert s.session_id.startswith("sess_")
    assert s.mode == SessionMode.EXECUTE
    d = s.to_dict()
    assert d["mode"] == "execute"


def test_task_state_transition():
    t = Task(intent="帮我写个文档")
    assert t.state == TaskState.SUGGESTED
    t.transition(TaskState.PLANNING)
    assert t.state == TaskState.PLANNING
    t.lock_owner("ou_xxx")
    assert t.owner_locked is True
    assert t.owner_open_id == "ou_xxx"


def test_step_lifecycle():
    s = Step(kind=StepKind.LLM_CALL)
    assert s.status == StepStatus.PENDING
    s.start()
    assert s.status == StepStatus.RUNNING
    s.complete(output={"text": "ok"})
    assert s.status == StepStatus.COMPLETED
    assert s.duration_ms >= 0


# ── IntentRouter ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_intent_explicit_pilot():
    router = IntentRouter()
    msg = ChatMessage(sender_open_id="u1", text="/pilot 帮我写个文档", chat_id="c1")
    r = await router.detect([msg])
    assert r.verdict == IntentVerdict.READY
    assert "explicit_pilot" in r.rule_hits


@pytest.mark.asyncio
async def test_intent_chat_not_silent_for_smalltalk():
    """V1.5 业务变更：闲聊不沉默，给友好回复（绝不沉默原则）."""
    router = IntentRouter()
    msg = ChatMessage(sender_open_id="u1", text="今天天气真好啊", chat_id="c1")
    r = await router.detect([msg])
    assert r.verdict == IntentVerdict.CHAT
    assert r.chat_reply  # 一定有回复文本


@pytest.mark.asyncio
async def test_intent_clarify_when_no_llm():
    """信息不足且无 LLM 判定时走 NEEDS_CLARIFY，避免空启 plan."""
    router = IntentRouter()
    msg = ChatMessage(sender_open_id="u1", text="帮我做个 PPT", chat_id="c1")
    r = await router.detect([msg])
    assert r.verdict == IntentVerdict.NEEDS_CLARIFY
    assert len(r.clarify_questions) >= 1


@pytest.mark.asyncio
async def test_intent_ready_short_circuit_when_info_rich():
    """信息充分（form 词 + 主题 + 长度）时闸门 3 短路 READY，不必走 LLM."""
    router = IntentRouter()  # 不注入 LLM 也应 READY
    msg = ChatMessage(
        sender_open_id="u1",
        text="帮我写一份关于 AI Agent 发展趋势的报告，给老板看",
        chat_id="c1",
    )
    r = await router.detect([msg])
    assert r.verdict == IntentVerdict.READY


@pytest.mark.asyncio
async def test_intent_llm_judge_overrides_when_short_text():
    """短文本 + 弱信号 → 走闸门 4，LLM 给出 ready 直接 READY."""
    async def fake_llm(text, history):
        return LLMJudgement(
            verdict="ready",
            is_task=True,
            task_type="report",
            goal="AI Agent",
            summary="AI Agent 报告",
            confidence=0.9,
        )

    router = IntentRouter(llm_judge=fake_llm)
    msg = ChatMessage(sender_open_id="u1", text="搞个东西", chat_id="c1")
    r = await router.detect([msg])
    assert r.verdict == IntentVerdict.READY
    assert r.llm_judgement is not None


# ── Planner ──────────────────────────────────────────────────────────────────


def test_plan_heuristic_doc_only():
    p = plan_from_intent("帮我写一份产品方案")
    assert isinstance(p, Plan)
    tools = [s.tool for s in p.steps]
    assert "doc.create" in tools
    assert "doc.append" in tools
    assert tools[-1] == "archive.bundle"


def test_plan_heuristic_three_in_one():
    p = plan_from_intent("产品方案 + 架构图 + 评审 PPT")
    tools = [s.tool for s in p.steps]
    assert "doc.create" in tools
    assert "canvas.create" in tools
    assert "slide.generate" in tools
    assert tools[-1] == "archive.bundle"


def test_plan_with_llm_fn():
    def fake_planner(prompt: str):
        return {"steps": [
            {"step_id": "s1", "tool": "doc.create", "description": "create",
             "args": {"title": "X"}, "depends_on": []},
            {"step_id": "s2", "tool": "archive.bundle", "description": "archive",
             "args": {}, "depends_on": ["s1"]},
        ]}

    p = plan_from_intent("写文档", llm_fn=fake_planner)
    assert len(p.steps) == 2
    assert p.steps[0].tool == "doc.create"
    assert p.steps[1].tool == "archive.bundle"


def test_plan_timely_keyword_triggers_web_search():
    """V1.5：意图含"今年/最新"等时效词，启发式自动插 web.search 第 0 步."""
    p = plan_from_intent("今年最新 AI Agent 趋势汇报 PPT")
    tools = [s.tool for s in p.steps]
    assert tools[0] == "web.search"
    # slide.generate 接收 ${s1.results} 参数
    slide_step = next(s for s in p.steps if s.tool == "slide.generate")
    assert slide_step.args.get("search_results") == "${s1.results}"


def test_plan_meta_forces_web_search_even_without_timely():
    """meta.needs_web_search=True 强制注入 web.search."""
    p = plan_from_intent("产品方案", meta={"needs_web_search": True})
    assert any(s.tool == "web.search" for s in p.steps)


def test_plan_no_web_search_when_no_timely():
    """普通意图不应自动插 web.search，避免无谓联网."""
    p = plan_from_intent("帮我写一份产品方案")
    assert not any(s.tool == "web.search" for s in p.steps)


# ── Orchestrator ─────────────────────────────────────────────────────────────


class FakeToolExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, *, tool_name, tool_input, ctx):
        self.calls.append((tool_name, tool_input))
        if tool_name == "doc.create":
            return {"doc_token": "DOC_ABC", "url": "https://feishu.cn/docx/DOC_ABC"}
        if tool_name == "doc.append":
            return {"doc_token": tool_input.get("doc_token", ""), "wrote_blocks": 50}
        if tool_name == "slide.generate":
            return {"slide_id": "slide_xxx", "pages": 8, "pptx_url": "/artifacts/slides/xxx.pptx"}
        if tool_name == "canvas.create":
            return {"canvas_id": "canvas_xxx", "url": "/artifacts/canvas/xxx"}
        if tool_name == "archive.bundle":
            return {"share_url": "https://feishu.cn/share/xxx"}
        return {"ok": True, "tool": tool_name}


@pytest.mark.asyncio
async def test_orchestrator_runs_simple_plan():
    p = plan_from_intent("帮我写一份产品方案")
    fx = FakeToolExecutor()
    events = []

    async def cb(ev):
        events.append(ev.kind)

    orch = Orchestrator(fx, on_event=cb)
    summary = await orch.run(p)

    assert summary["plan_id"] == p.plan_id
    assert len(summary["completed"]) == len(p.steps)
    assert "plan.start" in events
    assert "plan.done" in events
    assert any(e == "step.done" for e in events)


@pytest.mark.asyncio
async def test_orchestrator_resolves_placeholders():
    p = plan_from_intent("产品方案 + 架构图 + 评审 PPT")
    fx = FakeToolExecutor()
    orch = Orchestrator(fx)
    await orch.run(p)
    # archive.bundle 被调用且没有出错
    archive_calls = [c for c in fx.calls if c[0] == "archive.bundle"]
    assert len(archive_calls) == 1


@pytest.mark.asyncio
async def test_orchestrator_parallel_group():
    """parallel_group 相同的步骤应并行执行."""
    import time as t

    class SlowExecutor:
        def __init__(self):
            self.start_times = {}

        async def execute(self, *, tool_name, tool_input, ctx):
            self.start_times[tool_name] = t.monotonic()
            await asyncio.sleep(0.1)
            if tool_name == "doc.create":
                return {"doc_token": "X"}
            if tool_name == "doc.append":
                return {"wrote": 1}
            if tool_name == "canvas.create":
                return {"canvas_id": "C"}
            if tool_name == "slide.generate":
                return {"slide_id": "S"}
            if tool_name == "slide.rehearse":
                return {"speaker_notes": "ok"}
            return {"ok": True}

    p = plan_from_intent("产品方案 + 架构图 + 评审 PPT")
    ex = SlowExecutor()
    orch = Orchestrator(ex)
    await orch.run(p)

    # canvas.create 与 slide.generate 应几乎同时启动（parallel_group=g1）
    if "canvas.create" in ex.start_times and "slide.generate" in ex.start_times:
        delta = abs(ex.start_times["canvas.create"] - ex.start_times["slide.generate"])
        assert delta < 0.05, f"parallel group should run together, delta={delta}"
