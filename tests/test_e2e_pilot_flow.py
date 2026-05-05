"""E2E integration test: IM message -> intent detection -> task creation ->
context build -> planning -> orchestration -> delivery.

Tests the complete pilot flow without real Feishu APIs (all tools use local fallback).
"""

import time


def test_full_pilot_flow_explicit_command():
    """Test /pilot explicit command flow end-to-end."""
    from bot.pilot_router import PilotRouter

    sent_cards = []

    def mock_sender(target, card, *, scope="user"):
        sent_cards.append({"target": target, "card": card, "scope": scope})
        return f"msg-{len(sent_cards)}"

    router = PilotRouter(card_sender=mock_sender)
    result = router.handle_chat_message(
        sender_open_id="user_001",
        text="/pilot 帮我把本周的讨论整理成一份项目汇报文档",
        chat_id="chat_group_001",
        msg_id="msg_001",
    )

    assert result.handled is True
    assert result.verdict == "explicit_ready"
    assert result.task_id != ""
    assert len(sent_cards) >= 1


def test_full_pilot_flow_semantic_detection():
    """Test semantic intent detection flow."""
    from bot.pilot_router import PilotRouter

    sent_cards = []

    def mock_sender(target, card, *, scope="user"):
        sent_cards.append({"target": target, "card": card, "scope": scope})
        return f"msg-{len(sent_cards)}"

    router = PilotRouter(card_sender=mock_sender)

    # Simulate group chat conversation
    msgs = [
        ("user_a", "这个方案下周要汇报给老板"),
        ("user_b", "对，我们需要准备一下 PPT"),
        ("user_a", "把上周的讨论内容也整理一下"),
    ]
    results = []
    for sender, text in msgs:
        r = router.handle_chat_message(
            sender_open_id=sender,
            text=text,
            chat_id="chat_group_002",
            msg_id=f"msg_{len(results)}",
        )
        results.append(r)

    # At least one message should trigger intent detection
    handled_results = [r for r in results if r.handled]
    assert len(handled_results) > 0


def test_card_confirm_and_context_flow():
    """Test card button callback: confirm -> context -> plan."""
    from bot.pilot_router import PilotRouter

    sent_cards = []

    def mock_sender(target, card, *, scope="user"):
        sent_cards.append({"target": target, "card": card, "scope": scope})
        return f"msg-{len(sent_cards)}"

    router = PilotRouter(card_sender=mock_sender)

    # Create task first
    result = router.handle_chat_message(
        sender_open_id="user_001",
        text="/pilot 生成一份技术方案文档",
        chat_id="chat_001",
        msg_id="msg_001",
    )
    task_id = result.task_id
    assert task_id

    # Confirm the task
    confirm_result = router.handle_card_action(
        actor_open_id="user_001",
        action="pilot.task.confirm",
        value={"task_id": task_id},
    )
    assert confirm_result.handled is True
    assert confirm_result.verdict == "confirmed"

    # Confirm context
    ctx_result = router.handle_card_action(
        actor_open_id="user_001",
        action="pilot.ctx.confirm",
        value={"task_id": task_id},
    )
    assert ctx_result.handled is True
    assert ctx_result.verdict == "ctx_confirmed"


def test_task_assignment_flow():
    """Test owner assignment and claim flow."""
    from bot.pilot_router import PilotRouter

    sent_cards = []

    def mock_sender(target, card, *, scope="user"):
        sent_cards.append({"target": target, "card": card, "scope": scope})
        return f"msg-{len(sent_cards)}"

    router = PilotRouter(card_sender=mock_sender)

    result = router.handle_chat_message(
        sender_open_id="user_001",
        text="/pilot 准备季度复盘报告",
        chat_id="chat_001",
        msg_id="msg_001",
    )
    task_id = result.task_id

    # Open assign picker
    assign_result = router.handle_card_action(
        actor_open_id="user_001",
        action="pilot.task.assign",
        value={"task_id": task_id},
    )
    assert assign_result.verdict == "assign_picker"

    # Claim self
    claim_result = router.handle_card_action(
        actor_open_id="user_002",
        action="pilot.task.claim_self",
        value={"task_id": task_id},
    )
    assert claim_result.handled is True


def test_task_ignore_flow():
    """Test ignore and cooldown."""
    from bot.pilot_router import PilotRouter

    router = PilotRouter(card_sender=lambda *a, **kw: "ok")
    result = router.handle_chat_message(
        sender_open_id="user_001",
        text="/pilot 做个测试任务",
        chat_id="chat_001",
        msg_id="msg_001",
    )
    task_id = result.task_id

    ignore_result = router.handle_card_action(
        actor_open_id="user_001",
        action="pilot.task.ignore",
        value={"task_id": task_id},
    )
    assert ignore_result.verdict == "ignored"


def test_orchestrator_with_default_tools():
    """Test OrchestratorService runs with default tool registry."""
    from core.agent_pilot.application.orchestrator_service import OrchestratorService
    from core.agent_pilot.domain import Task, TaskEvent
    from core.agent_pilot.domain.context_pack import ContextPack, OutputRequirements
    from core.agent_pilot.tools import build_default_registry

    tools = build_default_registry()
    orch = OrchestratorService(tools=tools)

    # Create a task with plan
    task = Task(task_id="test-task-001", intent="生成一份技术方案文档", title="技术方案")
    task.owner_lock.owner_open_id = "user_001"

    # Attach context pack
    cp = ContextPack(
        task_id="test-task-001",
        task_goal="生成技术方案",
        owner_open_id="user_001",
        output_requirements=OutputRequirements(primary="doc"),
    )
    task.attach_context(cp, confirmed=True)

    # Advance to PLANNING state
    task.apply(TaskEvent.USER_CONFIRM, actor_open_id="user_001", enforce_owner_lock=False)
    task.apply(TaskEvent.USER_CONFIRM_CONTEXT, actor_open_id="user_001", enforce_owner_lock=False)

    # Create a minimal plan
    from core.agent_pilot.domain import Plan, PlanStep

    plan = Plan(
        plan_id="test-plan-001",
        task_id=task.task_id,
        owner_open_id="user_001",
        intent="生成技术方案",
        steps=[
            PlanStep(step_id="s1", tool="im.fetch_thread", description="拉取上下文", args={"limit": 5}),
            PlanStep(
                step_id="s2", tool="doc.create", description="创建文档", args={"title": "技术方案"}, depends_on=["s1"]
            ),
        ],
    )
    task.plan = plan

    # Run orchestrator
    result = orch.run(task)

    # Verify steps completed
    assert all(s.status in ("done", "failed") for s in result.plan.steps)
    # At least the first step should succeed
    assert result.plan.steps[0].status == "done"


def test_planner_heuristic_fallback():
    """Test PlannerService generates valid plan without LLM."""
    from core.agent_pilot.application import PlannerService
    from core.agent_pilot.domain import Task
    from core.agent_pilot.domain.context_pack import ContextPack, OutputRequirements

    planner = PlannerService(planner_factory=False)

    task = Task(task_id="test-task-002", intent="帮我生成一份活动复盘 PPT", title="活动复盘")
    task.owner_lock.owner_open_id = "user_001"
    cp = ContextPack(
        task_id="test-task-002",
        task_goal="活动复盘 PPT",
        owner_open_id="user_001",
        output_requirements=OutputRequirements(primary="ppt"),
    )
    task.attach_context(cp, confirmed=True)

    plan = planner.plan_for_task(task)
    assert plan is not None
    assert len(plan.steps) >= 3
    tool_names = [s.tool for s in plan.steps]
    assert "slide.generate" in tool_names


def test_state_machine_full_lifecycle():
    """Test task state machine through complete lifecycle."""
    from core.agent_pilot.domain import Task, TaskEvent, TaskState

    task = Task(task_id="test-task-003", intent="test", title="test")
    task.owner_lock.owner_open_id = "user_001"

    assert task.state == TaskState.SUGGESTED

    task.apply(TaskEvent.USER_CONFIRM, actor_open_id="user_001", enforce_owner_lock=False)
    assert task.state == TaskState.ASSIGNED

    task.apply(TaskEvent.USER_ADD_CONTEXT, actor_open_id="user_001", enforce_owner_lock=False)
    assert task.state == TaskState.CONTEXT_PENDING

    task.apply(TaskEvent.USER_CONFIRM_CONTEXT, actor_open_id="user_001", enforce_owner_lock=False)
    assert task.state == TaskState.PLANNING


def test_context_service_build():
    """Test ContextService builds valid ContextPack."""
    from core.agent_pilot.application import ContextBuildOptions, ContextService
    from core.agent_pilot.domain import SourceMessage

    svc = ContextService()
    opts = ContextBuildOptions(
        task_id="task-001",
        task_goal="写一份项目汇报",
        owner_open_id="user_001",
        output_primary="doc",
    )
    msgs = [
        SourceMessage(sender_open_id="user_a", text="项目进展不错", chat_id="chat_001"),
        SourceMessage(sender_open_id="user_b", text="下周要汇报给领导", chat_id="chat_001"),
    ]
    cp = svc.build(opts, im_messages=msgs)
    assert cp is not None
    assert cp.task_goal == "写一份项目汇报"
    assert len(cp.source_messages) == 2


def test_intent_detector_three_gates():
    """Test IntentDetector three-gate mechanism."""
    from core.agent_pilot.application import ChatMessage, IntentDetector, IntentVerdict

    detector = IntentDetector()
    msgs = [
        ChatMessage(
            sender_open_id="user_a",
            text="这个方案需要做个 PPT 汇报",
            chat_id="chat_001",
            msg_id="m1",
            ts=int(time.time()),
        ),
    ]
    candidate = detector.detect(msgs)
    assert candidate is not None
    assert candidate.verdict in (IntentVerdict.READY, IntentVerdict.NEEDS_CLARIFY, IntentVerdict.NOT_INTENT)
