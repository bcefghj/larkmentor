"""P5 · PlannerService + OrchestratorService 测试."""
from __future__ import annotations

import pytest

from core.agent_pilot.application import (
    ContextBuildOptions,
    ContextService,
    OrchestratorService,
    PatternSelection,
    PlannerService,
    ReasoningPattern,
    TaskService,
    select_reasoning_pattern,
)
from core.agent_pilot.application.orchestrator_service import OrchestratorConfig
from core.agent_pilot.application.task_service import TaskRepository
from core.agent_pilot.domain import (
    Plan as DomainPlan,
    PlanStep as DomainPlanStep,
    Task,
    TaskEvent,
    TaskState,
)


# ── 5 推理模式选择 ────────────────────────────────────────────────────────


@pytest.fixture
def task_with_ctx(tmp_path):
    svc = TaskService(repository=TaskRepository(root=str(tmp_path)))
    ctx_svc = ContextService(upload_root=str(tmp_path))

    def make(intent: str, primary: str = "doc", style: str = "",
              must_validate: bool = False):
        t = svc.create_task(intent=intent, owner_open_id="u1")
        cp = ctx_svc.build(ContextBuildOptions(
            task_id=t.task_id, task_goal=intent, owner_open_id="u1",
            output_primary=primary, output_style=style,
            must_validate=must_validate,
        ))
        t.attach_context(cp, confirmed=True)
        return t
    return make


def test_select_pattern_react_for_short_intent(task_with_ctx):
    t = task_with_ctx("帮我写")
    sel = select_reasoning_pattern(t, t.context_pack)
    assert sel.pattern == ReasoningPattern.REACT


def test_select_pattern_tot_for_explore(task_with_ctx):
    t = task_with_ctx("探索三种校园推广方案的优劣")
    sel = select_reasoning_pattern(t, t.context_pack)
    assert sel.pattern == ReasoningPattern.TOT


def test_select_pattern_debate_for_decision(task_with_ctx):
    t = task_with_ctx("正反方辩论：A 还是 B 方案")
    sel = select_reasoning_pattern(t, t.context_pack)
    assert sel.pattern == ReasoningPattern.DEBATE


def test_select_pattern_reflection_when_must_validate(task_with_ctx):
    t = task_with_ctx("做一份 Q2 战略汇报", must_validate=True)
    sel = select_reasoning_pattern(t, t.context_pack)
    assert sel.pattern == ReasoningPattern.REFLECTION


def test_select_pattern_default_cot(task_with_ctx):
    """中等长度的中文意图（>= 25 字）默认走 CoT."""
    t = task_with_ctx("把本周校园推广活动的群聊讨论整理成 8 页可汇报的方案文档")
    sel = select_reasoning_pattern(t, t.context_pack)
    assert sel.pattern == ReasoningPattern.COT


# ── PlannerService ─────────────────────────────────────────────────────────


def test_planner_service_requires_context(tmp_path):
    svc = TaskService(repository=TaskRepository(root=str(tmp_path)))
    ps = PlannerService(planner_factory=False)  # falsy = no backend
    t = svc.create_task(intent="x", owner_open_id="u1")
    with pytest.raises(ValueError):
        ps.plan_for_task(t)


def test_planner_service_heuristic_for_doc(task_with_ctx):
    t = task_with_ctx("把活动复盘整理成文档", primary="doc")
    # planner_factory=False forces fallback to heuristic
    ps = PlannerService(planner_factory=False)
    plan = ps.plan_for_task(t)
    assert plan.task_id == t.task_id
    assert plan.step_count() >= 2
    tools = [s.tool for s in plan.steps]
    assert "doc.create" in tools
    # 自动选择的推理模式应该被记录
    assert plan.reasoning_pattern in {p.value for p in ReasoningPattern}
    # 任务的 plan 字段应该被设置
    assert t.plan is plan


def test_planner_service_heuristic_for_ppt(task_with_ctx):
    t = task_with_ctx("做活动复盘汇报 PPT", primary="ppt")
    ps = PlannerService(planner_factory=False)
    plan = ps.plan_for_task(t)
    tools = [s.tool for s in plan.steps]
    assert "slide.generate" in tools


def test_planner_service_heuristic_for_canvas(task_with_ctx):
    t = task_with_ctx("把架构画到画板上", primary="canvas")
    ps = PlannerService(planner_factory=False)
    plan = ps.plan_for_task(t)
    tools = [s.tool for s in plan.steps]
    assert "canvas.create" in tools


def test_planner_service_logs_reasoning_choice(task_with_ctx):
    t = task_with_ctx("探索三种校园推广方案的优劣")
    ps = PlannerService(planner_factory=False)
    ps.plan_for_task(t)
    # 应该有一条 @pilot 的 thought log
    pilot_logs = [l for l in t.agent_logs if l.agent == "@pilot" and l.kind == "thought"]
    assert any("tot" in l.content for l in pilot_logs)


# ── OrchestratorService ───────────────────────────────────────────────────


def _ok_tool(step, ctx):
    return {"ok": True, "step_id": step.step_id, "tool": step.tool}


def _doc_create_tool(step, ctx):
    return {"doc_token": "DOC123", "url": "https://x.feishu.cn/docx/DOC123"}


def _doc_append_tool(step, ctx):
    return {"appended": True, "doc_token": ctx["resolved_args"].get("doc_token")}


def _failing_tool(step, ctx):
    raise RuntimeError("boom")


def test_orchestrator_runs_doc_plan(task_with_ctx):
    t = task_with_ctx("活动复盘整理成文档", primary="doc")
    ps = PlannerService(planner_factory=False)
    ps.plan_for_task(t)
    # 状态推进：ASSIGNED -> CONTEXT_PENDING -> PLANNING
    t.apply(TaskEvent.USER_CONFIRM, actor_open_id="u1")
    t.apply(TaskEvent.USER_CONFIRM_CONTEXT, actor_open_id="u1")
    assert t.state == TaskState.PLANNING

    orch = OrchestratorService(tools={
        "im.fetch_thread": _ok_tool,
        "doc.create": _doc_create_tool,
        "doc.append": _doc_append_tool,
        "archive.bundle": _ok_tool,
    })
    orch.run(t)
    # 全部步骤跑完
    assert all(s.status == "done" for s in t.plan.steps)
    # 状态机推进：PLANNING -> DOC_GENERATING -> REVIEWING
    assert t.state == TaskState.REVIEWING


def test_orchestrator_simulates_unregistered_tool(task_with_ctx):
    """tool 不在注册表 → 模拟 ok（dev mode）."""
    t = task_with_ctx("活动复盘", primary="doc")
    ps = PlannerService(planner_factory=False)
    ps.plan_for_task(t)
    t.apply(TaskEvent.USER_CONFIRM, actor_open_id="u1")
    t.apply(TaskEvent.USER_CONFIRM_CONTEXT, actor_open_id="u1")

    orch = OrchestratorService(tools={})  # empty registry
    orch.run(t)
    assert all(s.status == "done" for s in t.plan.steps)
    assert all(s.result.get("simulated") for s in t.plan.steps)


def test_orchestrator_records_failed_step(task_with_ctx):
    t = task_with_ctx("活动复盘", primary="doc")
    ps = PlannerService(planner_factory=False)
    ps.plan_for_task(t)
    t.apply(TaskEvent.USER_CONFIRM, actor_open_id="u1")
    t.apply(TaskEvent.USER_CONFIRM_CONTEXT, actor_open_id="u1")

    orch = OrchestratorService(tools={
        "im.fetch_thread": _ok_tool,
        "doc.create": _failing_tool,
    })
    orch.run(t)
    failed = [s for s in t.plan.steps if s.status == "failed"]
    assert len(failed) == 1
    assert "RuntimeError" in failed[0].error


def test_orchestrator_resolves_placeholders(task_with_ctx):
    t = task_with_ctx("活动复盘", primary="doc")
    ps = PlannerService(planner_factory=False)
    ps.plan_for_task(t)
    t.apply(TaskEvent.USER_CONFIRM, actor_open_id="u1")
    t.apply(TaskEvent.USER_CONFIRM_CONTEXT, actor_open_id="u1")

    orch = OrchestratorService(tools={
        "im.fetch_thread": _ok_tool,
        "doc.create": _doc_create_tool,
        "doc.append": _doc_append_tool,
        "archive.bundle": _ok_tool,
    })
    orch.run(t)
    # doc.append 应该 resolve 到 DOC123
    append_step = next(s for s in t.plan.steps if s.tool == "doc.append")
    assert append_step.result.get("doc_token") == "DOC123"


def test_orchestrator_event_bus_emits_events(task_with_ctx):
    from core.agent_pilot.domain import EventBus
    bus = EventBus()
    received = []
    bus.subscribe(received.append)

    t = task_with_ctx("活动复盘", primary="doc")
    ps = PlannerService(planner_factory=False)
    ps.plan_for_task(t)
    t.apply(TaskEvent.USER_CONFIRM, actor_open_id="u1", event_bus=bus)
    t.apply(TaskEvent.USER_CONFIRM_CONTEXT, actor_open_id="u1", event_bus=bus)

    orch = OrchestratorService(tools={
        "im.fetch_thread": _ok_tool,
        "doc.create": _doc_create_tool,
        "doc.append": _doc_append_tool,
        "archive.bundle": _ok_tool,
    }, event_bus=bus)
    orch.run(t)
    kinds = {e.event_kind for e in received}
    assert "plan_created" in kinds
    assert "step_started" in kinds
    assert "step_done" in kinds


def test_orchestrator_advance_state_disabled(task_with_ctx):
    t = task_with_ctx("活动复盘", primary="doc")
    ps = PlannerService(planner_factory=False)
    ps.plan_for_task(t)
    t.apply(TaskEvent.USER_CONFIRM, actor_open_id="u1")
    t.apply(TaskEvent.USER_CONFIRM_CONTEXT, actor_open_id="u1")

    orch = OrchestratorService(tools={
        "im.fetch_thread": _ok_tool,
        "doc.create": _doc_create_tool,
        "doc.append": _doc_append_tool,
        "archive.bundle": _ok_tool,
    })
    orch.run(t, advance_state=False)
    assert t.state == TaskState.PLANNING  # 没有自动推进
