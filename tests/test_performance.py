"""Performance tests: concurrent users, latency bounds, resource limits."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

os.environ.setdefault("FEISHU_APP_ID", "test")
os.environ.setdefault("FEISHU_APP_SECRET", "test")

pytestmark = pytest.mark.slow


class TestConcurrentPilotLaunch:
    """Simulate multiple users launching pilots concurrently."""

    def test_10_concurrent_launches(self):
        from core.agent_pilot.service import launch

        results = []
        errors = []

        def _launch(i):
            try:
                plan = launch(
                    f"并发任务 #{i}: 起草文档",
                    user_open_id=f"u_perf_{i}",
                    async_run=False,
                    execute=False,
                )
                return plan
            except Exception as e:
                errors.append(e)
                return None

        start = time.time()
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(_launch, i) for i in range(10)]
            for f in as_completed(futures):
                result = f.result()
                if result:
                    results.append(result)
        elapsed = time.time() - start

        assert len(errors) == 0, f"Errors during concurrent launch: {errors}"
        assert len(results) == 10
        assert elapsed < 10.0, f"10 concurrent launches took {elapsed:.1f}s (should be < 10s)"

    def test_plan_generation_latency(self):
        from core.agent_pilot.planner import plan_from_intent

        intents = [
            "帮我整理会议纪要",
            "写一份产品方案 PPT",
            "把讨论做成架构图",
            "起草一份技术评审文档",
            "做一个项目复盘总结",
        ]

        latencies = []
        for intent in intents:
            start = time.time()
            plan = plan_from_intent(intent, user_open_id="u_latency_test")
            latencies.append(time.time() - start)
            assert plan is not None

        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        assert avg_latency < 2.0, f"Average plan generation: {avg_latency:.2f}s"
        assert max_latency < 5.0, f"Max plan generation: {max_latency:.2f}s"


class TestMemoryPressure:
    """Test behavior under memory pressure."""

    def test_large_context_handling(self):
        from core.agent_pilot.domain import ContextPack, SourceMessage

        messages = [
            SourceMessage(
                msg_id=f"m_{i}",
                sender_open_id="u_sender",
                text=f"这是第 {i} 条消息，包含一些讨论内容。" * 10,
                ts=int(time.time()) - (100 - i),
            )
            for i in range(100)
        ]

        cp = ContextPack(
            task_goal="处理大量消息",
            source_messages=messages,
        )
        assert len(cp.source_messages) == 100
        assert cp.has_min_info()

    def test_many_tasks_list_performance(self):
        from core.agent_pilot.service import launch, list_plans

        for i in range(20):
            launch(
                f"batch task {i}",
                user_open_id="u_batch",
                async_run=False,
                execute=False,
            )

        start = time.time()
        plans = list_plans(user_open_id="u_batch", limit=20)
        elapsed = time.time() - start

        assert len(plans) >= 20
        assert elapsed < 2.0, f"Listing 20 plans took {elapsed:.2f}s"


class TestChaosResilience:
    """Chaos tests: simulate failures and verify graceful degradation."""

    def test_orchestrator_handles_tool_failure(self):
        from core.agent_pilot.planner import Plan, PlanStep
        from core.agent_pilot.orchestrator import PilotOrchestrator

        def failing_tool(step, ctx):
            raise RuntimeError("simulated tool failure")

        orch = PilotOrchestrator(tool_registry={"doc.create": failing_tool})
        plan = Plan(
            plan_id="chaos_1",
            intent="test chaos",
            user_open_id="u_chaos",
            steps=[
                PlanStep(step_id="s1", tool="doc.create", description="will fail"),
            ],
        )
        result = orch.run(plan)
        assert result.steps[0].status == "failed"
        assert "simulated tool failure" in result.steps[0].error

    def test_orchestrator_handles_timeout_tool(self):
        import signal
        from core.agent_pilot.planner import Plan, PlanStep
        from core.agent_pilot.orchestrator import PilotOrchestrator

        def slow_tool(step, ctx):
            time.sleep(0.5)
            return {"result": "slow but ok"}

        orch = PilotOrchestrator(tool_registry={"doc.create": slow_tool})
        plan = Plan(
            plan_id="chaos_2",
            intent="slow tool",
            user_open_id="u_chaos",
            steps=[
                PlanStep(step_id="s1", tool="doc.create", description="slow"),
            ],
        )
        result = orch.run(plan)
        assert result.steps[0].status == "done"

    def test_orchestrator_skips_missing_tool(self):
        from core.agent_pilot.planner import Plan, PlanStep
        from core.agent_pilot.orchestrator import PilotOrchestrator

        orch = PilotOrchestrator(tool_registry={})
        plan = Plan(
            plan_id="chaos_3",
            intent="missing tool",
            user_open_id="u_chaos",
            steps=[
                PlanStep(step_id="s1", tool="nonexistent.tool", description="missing"),
            ],
        )
        result = orch.run(plan)
        assert result.steps[0].status == "failed"
        assert "ToolNotRegisteredError" in result.steps[0].error

    def test_event_bus_handles_subscriber_failure(self):
        from core.agent_pilot.domain.events import EventBus, make_event

        bus = EventBus()
        good_events = []

        def bad_handler(e):
            raise RuntimeError("subscriber crash")

        def good_handler(e):
            good_events.append(e)

        bus.subscribe(bad_handler)
        bus.subscribe(good_handler)

        bus.publish(make_event("test", "task_1"))
        assert len(good_events) == 1
