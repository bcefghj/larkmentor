"""Tests for the harness components: ToolRegistry, HookSystem, Permissions, etc."""

import os
import pytest

os.environ.setdefault("FEISHU_APP_ID", "test")
os.environ.setdefault("FEISHU_APP_SECRET", "test")


class TestToolRegistry:
    """Test the harness ToolRegistry."""

    def test_default_registry_exists(self):
        from core.agent_pilot.harness import default_registry
        reg = default_registry()
        assert reg is not None

    def test_build_tool_creates_spec(self):
        from core.agent_pilot.harness import build_tool

        spec = build_tool(
            name="test.tool",
            description="A test tool",
            fn=lambda ctx: {"result": "ok"},
        )
        assert spec.name == "test.tool"
        assert spec.description == "A test tool"

    def test_registry_register_and_lookup(self):
        from core.agent_pilot.harness import ToolRegistry, build_tool

        reg = ToolRegistry()
        spec = build_tool(name="my.tool", description="desc", fn=lambda ctx: {})
        reg.register(spec)
        found = reg.get("my.tool")
        assert found is not None
        assert found.name == "my.tool"

    def test_registry_list(self):
        from core.agent_pilot.harness import ToolRegistry, build_tool

        reg = ToolRegistry()
        reg.register(build_tool("a.tool", "desc A", lambda ctx: {}))
        reg.register(build_tool("b.tool", "desc B", lambda ctx: {}))
        all_tools = reg.list()
        assert len(all_tools) >= 2
        names = [t.name for t in all_tools]
        assert "a.tool" in names
        assert "b.tool" in names

    def test_registry_has(self):
        from core.agent_pilot.harness import ToolRegistry, build_tool

        reg = ToolRegistry()
        reg.register(build_tool("check.tool", "desc", lambda ctx: {}))
        assert reg.has("check.tool")
        assert not reg.has("nonexistent")

    def test_registry_names(self):
        from core.agent_pilot.harness import ToolRegistry, build_tool

        reg = ToolRegistry()
        reg.register(build_tool("x.tool", "desc", lambda ctx: {}))
        assert "x.tool" in reg.names()

    def test_registry_unregister(self):
        from core.agent_pilot.harness import ToolRegistry, build_tool

        reg = ToolRegistry()
        reg.register(build_tool("temp.tool", "desc", lambda ctx: {}))
        assert reg.has("temp.tool")
        reg.unregister("temp.tool")
        assert not reg.has("temp.tool")


class TestHookRegistry:
    """Test the hook lifecycle system."""

    def test_default_hook_registry_exists(self):
        from core.agent_pilot.harness import default_hook_registry
        reg = default_hook_registry()
        assert reg is not None

    def test_hook_registration(self):
        from core.agent_pilot.harness import HookRegistry, HookEvent

        reg = HookRegistry()
        reg.register(HookEvent.PRE_TOOL_USE, lambda ctx: None)
        reg.register(HookEvent.POST_TOOL_USE, lambda ctx: None)
        # Hooks registered without error
        assert True

    def test_hook_events_exist(self):
        from core.agent_pilot.harness import HookEvent

        assert hasattr(HookEvent, "SESSION_START")
        assert hasattr(HookEvent, "PRE_TOOL_USE")
        assert hasattr(HookEvent, "POST_TOOL_USE")
        assert hasattr(HookEvent, "PRE_COMPACT")
        assert hasattr(HookEvent, "STOP")


class TestPermissionGate:
    """Test the permission system."""

    def test_default_permission_gate_exists(self):
        from core.agent_pilot.harness import default_permission_gate
        gate = default_permission_gate()
        assert gate is not None

    def test_permission_modes(self):
        from core.agent_pilot.harness import PermissionMode

        assert hasattr(PermissionMode, "DEFAULT")
        assert hasattr(PermissionMode, "AUTO")
        assert hasattr(PermissionMode, "BYPASS")


class TestContextManager:
    """Test context management."""

    def test_context_manager_init(self):
        from core.agent_pilot.harness import ContextManager

        cm = ContextManager()
        assert cm is not None

    def test_context_snapshot_creation(self):
        from core.agent_pilot.harness import ContextSnapshot

        snap = ContextSnapshot(
            messages=[],
            token_count=0,
            total_budget=100000,
        )
        assert snap.token_count == 0
        assert snap.total_budget == 100000


class TestMemoryLayer:
    """Test memory integration."""

    def test_default_memory_exists(self):
        from core.agent_pilot.harness import default_memory
        mem = default_memory()
        assert mem is not None


class TestSkillsLoader:
    """Test skills loading."""

    def test_default_skills_exists(self):
        from core.agent_pilot.harness import default_skills
        skills = default_skills()
        assert skills is not None


class TestMCPClient:
    """Test MCP client initialization."""

    def test_default_mcp_manager_exists(self):
        from core.agent_pilot.harness import default_mcp_manager
        mgr = default_mcp_manager()
        assert mgr is not None


class TestSubagentRunner:
    """Test subagent functionality."""

    def test_subagent_runner_init(self):
        from core.agent_pilot.harness import SubagentRunner

        runner = SubagentRunner(runner_fn=lambda prompt, ctx: {"summary": "done"})
        assert runner is not None

    def test_subagent_result_structure(self):
        from core.agent_pilot.harness import SubagentResult

        result = SubagentResult(
            subagent_id="sub_1",
            prompt="do something",
            summary="completed",
            facts={"key": "val"},
        )
        assert result.summary == "completed"
        assert result.subagent_id == "sub_1"


class TestStreamingExecutor:
    """Test streaming tool executor."""

    def test_streaming_executor_init(self):
        from core.agent_pilot.harness import StreamingToolExecutor, ToolRegistry

        reg = ToolRegistry()
        executor = StreamingToolExecutor(registry=reg)
        assert executor is not None


class TestConversationOrchestrator:
    """Test the main orchestration engine."""

    def test_orchestrator_init(self):
        from core.agent_pilot.harness import ConversationOrchestrator

        orch = ConversationOrchestrator()
        assert orch is not None

    def test_orchestrator_state_class(self):
        from core.agent_pilot.harness import OrchestratorState
        from core.agent_pilot.planner import Plan

        plan = Plan(plan_id="test", intent="test", user_open_id="u", steps=[])
        state = OrchestratorState(plan=plan)
        assert hasattr(state, "summary")
        assert hasattr(state, "verdict")

    def test_default_orchestrator(self):
        from core.agent_pilot.harness import default_orchestrator

        orch = default_orchestrator()
        assert orch is not None
