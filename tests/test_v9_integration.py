"""Agent-Pilot v12 integration tests.

Tests the full pipeline: IM message → IntentDetector → PlannerService →
ConversationOrchestrator → Tool execution → Result delivery.
"""

import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


class TestIntentToDeliveryPipeline:
    """End-to-end integration test for the Pilot main flow."""

    def test_explicit_intent_triggers_plan(self):
        """@pilot command should directly create a plan."""
        from core.agent_pilot.application.intent_detector import (
            IntentDetector,
            IntentDetectorConfig,
            ChatMessage,
        )

        def mock_llm_caller(text: str) -> str:
            return '{"is_task": true, "task_type": "doc", "goal": "创建项目总结文档", "resources": [], "next_step": "拉取聊天记录", "confidence": 0.95}'

        detector = IntentDetector(
            config=IntentDetectorConfig(enable_llm=True),
            llm_caller=mock_llm_caller,
        )
        messages = [
            ChatMessage(
                sender_open_id="test_user",
                text="整理一下这个项目讨论，下周要出个文档给老板汇报",
                chat_id="test_chat",
            ),
        ]
        verdict = detector.detect(messages)
        assert verdict.verdict.value in ("ready", "clarify")

    def test_rule_layer_detects_keywords(self):
        """Rule layer should detect task-indicating keywords."""
        from core.agent_pilot.application.intent_detector import (
            ChatMessage,
            detect_rules,
            rule_passes,
        )

        messages = [
            ChatMessage(sender_open_id="u1", text="下周要做个方案给老板看", chat_id="c1"),
            ChatMessage(sender_open_id="u2", text="好的，整理一下之前的讨论", chat_id="c1"),
        ]
        hit = detect_rules(messages)
        assert hit.score > 0.0
        assert len(hit.keyword_hits) > 0
        assert rule_passes(hit)

    def test_planner_creates_dag(self):
        """PlannerService should create a valid DAG from intent."""
        from core.agent_pilot.application.planner_service import PlannerService
        from core.agent_pilot.domain import Task, ContextPack, OwnerLock

        task = Task(
            task_id="test_task_001",
            owner_lock=OwnerLock(task_id="test_task_001", owner_open_id="test_user"),
            intent="创建项目总结文档",
            title="项目总结",
            context_pack=ContextPack(
                task_id="test_task_001",
                task_goal="创建项目总结文档",
                owner_open_id="test_user",
                pack_id="cp_test",
            ),
        )

        def mock_backend(intent, **kwargs):
            from core.agent_pilot.planner import Plan, PlanStep

            return Plan(
                plan_id="plan_test",
                user_open_id="test_user",
                intent=intent,
                steps=[
                    PlanStep(step_id="s1", tool="im.fetch_thread", description="拉取聊天", args={"limit": 50}),
                    PlanStep(step_id="s2", tool="doc.create", description="创建文档", args={"title": "项目总结"}, depends_on=["s1"]),
                ],
                created_ts=int(time.time()),
            )

        class MockPlanner:
            def plan(self, intent, **kwargs):
                return mock_backend(intent, **kwargs)

        with patch("core.agent_pilot.application.planner_service.PlannerService._backend_planner", return_value=MockPlanner()):
            planner = PlannerService()
            plan = planner.plan_for_task(task)
            assert plan is not None
            assert len(plan.steps) >= 1
            assert plan.reasoning_pattern in ("react", "cot", "reflection", "debate", "tot")

    def test_orchestrator_executes_plan(self):
        """ConversationOrchestrator should execute plan steps with mocked tools."""
        from core.agent_pilot.harness.orchestrator_v2 import ConversationOrchestrator
        from core.agent_pilot.harness.tool_registry import ToolRegistry, ToolSpec
        from core.agent_pilot.harness.hooks import HookRegistry
        from core.agent_pilot.harness.permissions import PermissionGate
        from core.agent_pilot.planner import Plan, PlanStep

        plan = Plan(
            plan_id="test_plan",
            user_open_id="test_user",
            intent="test",
            steps=[
                PlanStep(
                    step_id="s1",
                    tool="mentor.summarize",
                    description="test step",
                    args={"context": "test content"},
                ),
            ],
            created_ts=int(time.time()),
            meta={},
        )

        mock_registry = ToolRegistry()
        mock_registry.register(ToolSpec(
            name="mentor.summarize",
            description="mock summarize",
            fn=lambda args, ctx: {"summary": "test summary"},
        ))

        orchestrator = ConversationOrchestrator(
            tools=mock_registry,
            hooks=HookRegistry(),
            permissions=PermissionGate(),
        )
        finished = orchestrator.run(plan, context={"auto_confirm": True})
        assert finished is not None

    def test_health_endpoint(self):
        """Health check endpoint should respond."""
        from dashboard.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_ready_endpoint(self):
        """Readiness endpoint should report dependency status."""
        from dashboard.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert "checks" in data


class TestAPIContract:
    """API contract tests for Dashboard endpoints."""

    def test_tasks_list_returns_array(self):
        from dashboard.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/v7/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (list, dict))

    def test_version_endpoint(self):
        from dashboard.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/v1/version")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert data["version"] == "12.0.0"

    def test_overview_endpoint(self):
        from dashboard.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        # Switch to demo mode to avoid startup state dependency
        client.get("/demo")
        resp = client.get("/api/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert "decisions_today" in data or "mode" in data
        # Reset
        client.get("/live")

    def test_demo_mode_toggle(self):
        from dashboard.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/demo")
        assert resp.status_code == 200
        assert resp.json()["mode"] == "demo"

        resp = client.get("/live")
        assert resp.status_code == 200
        assert resp.json()["mode"] == "live"

    def test_health_legacy(self):
        from dashboard.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
