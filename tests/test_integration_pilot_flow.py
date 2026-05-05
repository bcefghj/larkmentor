"""Integration tests: full IM → Plan → Doc → Slide flow.

Tests the complete pipeline WITHOUT external services (Feishu/LLM mocked).
"""

import os

import pytest

os.environ.setdefault("FEISHU_APP_ID", "test")
os.environ.setdefault("FEISHU_APP_SECRET", "test")


class TestFullPilotFlow:
    """Integration: simulate plan creation and execution without LLM calls."""

    def test_planner_creates_valid_plan(self):
        from core.agent_pilot.planner import PilotPlanner

        planner = PilotPlanner(chat_json_fn=lambda *a, **k: {})
        plan = planner.plan("帮我把本周讨论整理成产品方案", user_open_id="u_integration")

        assert plan is not None
        assert plan.plan_id
        assert len(plan.steps) > 0

    def test_orchestrator_runs_plan_with_mock_tools(self):
        from core.agent_pilot.orchestrator import PilotOrchestrator
        from core.agent_pilot.planner import PilotPlanner

        planner = PilotPlanner(chat_json_fn=lambda *a, **k: {})
        plan = planner.plan("起草一份Q3产品规划文档", user_open_id="u_plan_mode")
        mock_tools = {s.tool: (lambda step, ctx: {"mock": True}) for s in plan.steps}
        orch = PilotOrchestrator(tool_registry=mock_tools)
        result = orch.run(plan)

        assert all(s.status == "done" for s in result.steps)

    def test_plan_persistence(self):
        from core.agent_pilot.planner import PilotPlanner
        from core.agent_pilot.service import _persist, get_plan

        planner = PilotPlanner(chat_json_fn=lambda *a, **k: {})
        plan = planner.plan("写一个技术评审PPT", user_open_id="u_persist")
        _persist(plan, phase="planned")

        retrieved = get_plan(plan.plan_id)
        assert retrieved is not None
        assert retrieved.intent == plan.intent

    def test_list_plans(self):
        from core.agent_pilot.planner import PilotPlanner
        from core.agent_pilot.service import _persist, list_plans

        planner = PilotPlanner(chat_json_fn=lambda *a, **k: {})
        plan = planner.plan("test listing", user_open_id="u_list_test_2")
        _persist(plan, phase="planned")

        plans = list_plans(user_open_id="u_list_test_2")
        assert len(plans) >= 1


class TestOrchestratorUnified:
    """Test that the unified orchestrator path works correctly."""

    def test_get_orchestrator_returns_conversation_orchestrator(self):
        from core.agent_pilot.harness import ConversationOrchestrator
        from core.agent_pilot.service import get_orchestrator

        orch = get_orchestrator()
        assert isinstance(orch, ConversationOrchestrator)

    def test_orchestrator_singleton(self):
        from core.agent_pilot.service import get_orchestrator

        o1 = get_orchestrator()
        o2 = get_orchestrator()
        assert o1 is o2


class TestConfigValidation:
    """Test that config loads and validates correctly."""

    def test_config_loads(self):
        from config import Config

        assert Config.FEISHU_APP_ID is not None
        assert Config.ARK_BASE_URL.startswith("http")

    def test_config_types(self):
        from config import Config

        assert isinstance(Config.DASHBOARD_PORT, int)
        assert isinstance(Config.THRESHOLD_P0, float)
        assert isinstance(Config.URGENT_KEYWORDS, list)


class TestDomainStateMachine:
    """Test domain state machine transitions end-to-end."""

    def test_full_lifecycle(self):
        from core.agent_pilot.domain import Task, TaskEvent, TaskState

        task = Task(
            task_id="t_lifecycle",
            intent="test full lifecycle",
            source_chat_id="chat_test",
        )
        assert task.state == TaskState.SUGGESTED

        task.apply(TaskEvent.USER_CONFIRM, actor_open_id="u1")
        assert task.state == TaskState.ASSIGNED

        task.apply(TaskEvent.USER_ADD_CONTEXT, actor_open_id="u1")
        assert task.state == TaskState.CONTEXT_PENDING

        task.apply(TaskEvent.USER_CONFIRM_CONTEXT, actor_open_id="u1")
        assert task.state == TaskState.PLANNING

    def test_invalid_transition_raises(self):
        from core.agent_pilot.domain import Task, TaskEvent
        from core.agent_pilot.domain.errors import InvalidTransitionError

        task = Task(
            task_id="t_invalid",
            intent="test invalid",
            source_chat_id="chat_test",
        )
        with pytest.raises(InvalidTransitionError):
            task.apply(TaskEvent.GENERATION_DONE, actor_open_id="u1")


class TestEventBus:
    """Test the domain event bus works correctly."""

    def test_publish_and_subscribe(self):
        from core.agent_pilot.domain.events import EventBus, make_event

        bus = EventBus()
        received = []

        bus.subscribe(lambda e: received.append(e))
        bus.publish(make_event("test_event", "task_123", data={"key": "val"}))

        assert len(received) == 1
        assert received[0].event_kind == "test_event"
        assert received[0].task_id == "task_123"


class TestPlannerService:
    """Test planner service creates valid plans."""

    def test_planner_creates_plan(self):
        from core.agent_pilot.planner import PilotPlanner

        planner = PilotPlanner(chat_json_fn=lambda *a, **k: {})
        plan = planner.plan("帮我起草一份项目方案", user_open_id="u_planner_test")
        assert plan is not None
        assert len(plan.steps) > 0


class TestOrchestratorServiceBroadcasting:
    """Test OrchestratorService broadcasting to streaming cards."""

    def test_broadcaster_receives_events(self):
        from core.agent_pilot.application.orchestrator_service import (
            OrchestratorConfig,
            OrchestratorService,
        )
        from core.agent_pilot.domain import Plan as DomainPlan, PlanStep as DomainPlanStep, Task

        events = []
        svc = OrchestratorService(
            tools={"test.tool": lambda step, ctx: {"ok": True}},
            config=OrchestratorConfig(demo_mode=True),
        )
        svc.set_broadcaster(lambda ev: events.append(ev))

        task = Task(task_id="t_broadcast", intent="test broadcasting", source_chat_id="chat_test")
        task.apply_unsafe(state="planning")
        task.plan = DomainPlan(
            plan_id="p_broadcast",
            intent="test",
            steps=[
                DomainPlanStep(step_id="s1", tool="test.tool", description="test step"),
            ],
            owner_open_id="u1",
        )

        svc.run(task, advance_state=False)

        kinds = [e.get("kind") for e in events]
        assert "plan_started" in kinds
        assert "step_started" in kinds
        assert "step_done" in kinds
        assert "plan_done" in kinds

    def test_orchestrator_property_returns_self(self):
        from core.agent_pilot.application.orchestrator_service import OrchestratorService

        svc = OrchestratorService()
        assert svc.orchestrator is svc

    def test_demo_mode_simulates_missing_tools(self):
        from core.agent_pilot.application.orchestrator_service import (
            OrchestratorConfig,
            OrchestratorService,
        )
        from core.agent_pilot.domain import Plan as DomainPlan, PlanStep as DomainPlanStep, Task

        svc = OrchestratorService(
            tools={},
            config=OrchestratorConfig(demo_mode=True),
        )
        task = Task(task_id="t_demo", intent="test demo", source_chat_id="c")
        task.apply_unsafe(state="planning")
        task.plan = DomainPlan(
            plan_id="p_demo",
            intent="test",
            steps=[PlanStep(step_id="s1", tool="missing.tool", description="test")],
            owner_open_id="u1",
        )
        result = svc.run(task, advance_state=False)
        assert result.plan.steps[0].status == "done"
        assert result.plan.steps[0].result.get("simulated") is True


class TestMultiProviderRouter:
    """Test multi-model provider routing."""

    def test_provider_router_init(self):
        from agent.providers import ProviderRouter

        router = ProviderRouter()
        assert router is not None
        assert hasattr(router, "chat")

    def test_provider_router_has_fallback(self):
        from agent.providers import default_providers

        providers = default_providers()
        assert providers is not None
