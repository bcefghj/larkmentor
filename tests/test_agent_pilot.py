"""Tests for the Agent-Pilot Planner + Orchestrator (Scenario A-F)."""

from __future__ import annotations

import pytest

from core.agent_pilot.planner import (
    PilotPlanner, Plan, PlanStep, KNOWN_TOOLS, plan_from_intent,
)
from core.agent_pilot.orchestrator import PilotOrchestrator, ExecutionEvent
from core.agent_pilot.tools import build_default_registry
from core.agent_pilot.scenarios import ScenarioRegistry


# ─────────────────────────── Planner ────────────────────────────

def test_planner_heuristic_produces_doc_slide_dag_when_no_llm():
    planner = PilotPlanner(chat_json_fn=lambda *a, **k: {})  # force fallback
    plan = planner.plan("把本周讨论做成产品方案和评审 PPT",
                        user_open_id="ou_demo_xxx")
    assert plan.plan_id.startswith("plan_")
    assert plan.user_open_id == "ou_demo_xxx"
    tools = [s.tool for s in plan.steps]
    assert "doc.create" in tools
    assert "slide.generate" in tools
    assert tools[-1] == "archive.bundle"
    # every tool must be recognised
    for t in tools:
        assert t in KNOWN_TOOLS


def test_planner_heuristic_adds_canvas_when_user_asks_for_architecture_image():
    planner = PilotPlanner(chat_json_fn=lambda *a, **k: {})
    plan = planner.plan("帮我画一张架构图", user_open_id="ou_demo")
    tools = [s.tool for s in plan.steps]
    assert "canvas.create" in tools
    assert "canvas.add_shape" in tools


def test_planner_accepts_llm_output():
    fake = {
        "steps": [
            {"step_id": "s1", "tool": "im.fetch_thread",
             "description": "pull context", "args": {"limit": 10}},
            {"step_id": "s2", "tool": "doc.create",
             "description": "make doc", "depends_on": ["s1"]},
            {"step_id": "s3", "tool": "archive.bundle",
             "description": "bundle", "depends_on": ["s2"]},
        ]
    }
    planner = PilotPlanner(chat_json_fn=lambda *a, **k: fake)
    # Disable the advanced-clarify prepend so we only test the LLM path
    plan = planner.plan("帮我起草需求文档", allow_clarify=False)
    assert [s.tool for s in plan.steps] == [
        "im.fetch_thread", "doc.create", "archive.bundle"
    ]


def test_planner_filters_unknown_tools_from_llm():
    fake = {
        "steps": [
            {"step_id": "s1", "tool": "bogus.tool", "description": "x"},
            {"step_id": "s2", "tool": "doc.create", "description": "make doc"},
        ]
    }
    planner = PilotPlanner(chat_json_fn=lambda *a, **k: fake)
    plan = planner.plan("做个文档")
    assert all(s.tool != "bogus.tool" for s in plan.steps)
    assert plan.steps[-1].tool == "archive.bundle"


def test_planner_rejects_empty_intent():
    planner = PilotPlanner(chat_json_fn=lambda *a, **k: {})
    with pytest.raises(ValueError):
        planner.plan("")


# ─────────────────────────── Orchestrator ───────────────────────

def test_orchestrator_runs_simulated_steps_in_topological_order():
    planner = PilotPlanner(chat_json_fn=lambda *a, **k: {})
    plan = planner.plan("起草需求并生成 PPT", user_open_id="ou_demo")
    # No tools registered → orchestrator uses deterministic simulation
    orch = PilotOrchestrator()
    captured = []
    orch.set_broadcaster(lambda ev: captured.append(ev))
    orch.run(plan)

    assert all(s.status == "done" for s in plan.steps), [
        (s.step_id, s.status, s.error) for s in plan.steps
    ]
    # depends_on strictly before
    done_ts = {s.step_id: s.finished_ts for s in plan.steps}
    for s in plan.steps:
        for dep in s.depends_on:
            assert done_ts[dep] <= s.finished_ts

    kinds = [e.kind for e in captured]
    assert kinds[0] == "plan_started"
    assert kinds[-1] == "plan_done"
    assert "step_done" in kinds


def test_orchestrator_broadcaster_receives_all_step_events():
    planner = PilotPlanner(chat_json_fn=lambda *a, **k: {})
    plan = planner.plan("写文档 + PPT")
    orch = PilotOrchestrator()
    events = []
    orch.set_broadcaster(lambda ev: events.append(ev.to_dict()))
    orch.run(plan)
    step_events = [e for e in events if e["kind"] in ("step_started", "step_done")]
    # at least 2 events per step
    assert len(step_events) >= 2 * len(plan.steps) - 2


def test_orchestrator_uses_real_registered_tool():
    planner = PilotPlanner(chat_json_fn=lambda *a, **k: {})
    plan = planner.plan("帮我做个 PPT")
    called = {"count": 0}

    def my_slide_gen(step, ctx):
        called["count"] += 1
        return {"slide_id": "real_slide_1", "pptx_url": "/real/path.pptx",
                "pdf_url": "/real/path.pdf", "pages": 5}

    registry = build_default_registry()
    registry["slide.generate"] = my_slide_gen
    orch = PilotOrchestrator(tool_registry=registry)
    orch.run(plan)
    assert called["count"] == 1


def test_plan_from_intent_convenience_wrapper_returns_plan():
    plan = plan_from_intent("做个画布", user_open_id="ou_abc")
    assert isinstance(plan, Plan)
    assert plan.user_open_id == "ou_abc"
    assert any(s.tool == "archive.bundle" for s in plan.steps)


# ─────────────────────────── Scenarios ───────────────────────

def test_scenario_registry_has_all_six_scenarios():
    keys = {s.key for s in ScenarioRegistry.all()}
    assert keys == {"A_intent", "B_planner", "C_doc_canvas",
                    "D_slide", "E_sync", "F_delivery"}


def test_scenario_registry_lookup():
    s = ScenarioRegistry.get("C_doc_canvas")
    assert s is not None
    assert "doc.create" in s.entry_tools
    assert "canvas.create" in s.entry_tools
