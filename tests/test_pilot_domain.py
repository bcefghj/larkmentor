"""P2 · Pilot 领域层单元测试.

覆盖：
- 10 状态枚举完整性
- 状态转移合法/非法
- 5 类基本路径（IM 主动识别 → 任务卡 → 指派 → 上下文 → Doc/PPT/Canvas → Reviewing → Delivered）
- Owner 锁定不变量
- ContextPack 最小信息闸门
- Domain Event 总线发布/订阅/隔离
"""
from __future__ import annotations

import pytest

from core.agent_pilot.domain import (
    Artifact,
    ArtifactKind,
    ContextPack,
    DomainEvent,
    EventBus,
    InvalidTransitionError,
    MaterialKind,
    OwnerLockedError,
    SourceMessage,
    Task,
    TaskEvent,
    TaskState,
    UserMaterial,
    can_transition,
    transition,
)
from core.agent_pilot.domain.context_pack import (
    Constraints,
    OutputRequirements,
)
from core.agent_pilot.domain.events import (
    EVT_TASK_CREATED,
    EVT_TASK_STATE_CHANGED,
    EVT_TASK_ASSIGNED,
    make_event,
)
from core.agent_pilot.domain.state_machine import legal_events, transition_count


# ── 枚举完整性 ─────────────────────────────────────────────────────────────


def test_state_enum_has_all_10_plus_2_states():
    expected = {
        "suggested", "assigned", "context_pending",
        "planning", "doc_generating", "ppt_generating", "canvas_generating",
        "reviewing", "delivered",
        "paused", "failed", "ignored",
    }
    assert {s.value for s in TaskState} == expected


def test_state_terminal_property():
    assert TaskState.DELIVERED.is_terminal
    assert TaskState.IGNORED.is_terminal
    assert TaskState.FAILED.is_terminal
    assert not TaskState.SUGGESTED.is_terminal


def test_state_active_property():
    assert TaskState.SUGGESTED.is_active
    assert TaskState.PLANNING.is_active
    assert not TaskState.PAUSED.is_active
    assert not TaskState.DELIVERED.is_active


def test_state_generating_property():
    assert TaskState.DOC_GENERATING.is_generating
    assert TaskState.PPT_GENERATING.is_generating
    assert TaskState.CANVAS_GENERATING.is_generating
    assert not TaskState.PLANNING.is_generating


def test_transition_count_at_least_30():
    """合法转移应该 >= 30 条；目前实现是 ~50 条。"""
    assert transition_count() >= 30


# ── 合法转移路径 ────────────────────────────────────────────────────────────


def test_happy_path_doc_only():
    """主流程 1：纯文档任务."""
    s = TaskState.SUGGESTED
    s = transition(s, TaskEvent.USER_CONFIRM)
    assert s == TaskState.ASSIGNED
    s = transition(s, TaskEvent.USER_ADD_CONTEXT)
    assert s == TaskState.CONTEXT_PENDING
    s = transition(s, TaskEvent.USER_CONFIRM_CONTEXT)
    assert s == TaskState.PLANNING
    s = transition(s, TaskEvent.PLAN_DONE_DOC)
    assert s == TaskState.DOC_GENERATING
    s = transition(s, TaskEvent.GENERATION_DONE)
    assert s == TaskState.REVIEWING
    s = transition(s, TaskEvent.USER_DELIVER)
    assert s == TaskState.DELIVERED


def test_happy_path_doc_plus_ppt():
    """主流程 2：文档 → PPT 后续."""
    s = TaskState.REVIEWING
    s = transition(s, TaskEvent.USER_REQUEST_PPT)
    assert s == TaskState.PPT_GENERATING
    s = transition(s, TaskEvent.GENERATION_DONE)
    assert s == TaskState.REVIEWING
    s = transition(s, TaskEvent.USER_DELIVER)
    assert s == TaskState.DELIVERED


def test_happy_path_canvas():
    """主流程 3：自由画布."""
    s = TaskState.PLANNING
    s = transition(s, TaskEvent.PLAN_DONE_CANVAS)
    assert s == TaskState.CANVAS_GENERATING
    s = transition(s, TaskEvent.GENERATION_DONE)
    assert s == TaskState.REVIEWING


def test_skip_context_pending():
    """主流程 4：用户跳过上下文确认直接进 Planning."""
    s = TaskState.ASSIGNED
    s = transition(s, TaskEvent.USER_SKIP_CONTEXT)
    assert s == TaskState.PLANNING


def test_ignore_from_suggested():
    """用户忽略路径."""
    s = TaskState.SUGGESTED
    s = transition(s, TaskEvent.USER_IGNORE)
    assert s == TaskState.IGNORED
    assert s.is_terminal


def test_pause_resume():
    s = TaskState.PLANNING
    s = transition(s, TaskEvent.USER_PAUSE)
    assert s == TaskState.PAUSED
    s = transition(s, TaskEvent.USER_RESUME)
    assert s == TaskState.PLANNING


def test_failed_then_retry():
    s = TaskState.PLANNING
    s = transition(s, TaskEvent.FATAL_ERROR)
    assert s == TaskState.FAILED
    s = transition(s, TaskEvent.USER_RETRY)
    assert s == TaskState.PLANNING


def test_context_insufficient_loops_back():
    s = TaskState.SUGGESTED
    s = transition(s, TaskEvent.CONTEXT_INSUFFICIENT)
    assert s == TaskState.CONTEXT_PENDING


# ── 非法转移 ────────────────────────────────────────────────────────────────


def test_illegal_delivered_back_to_planning():
    with pytest.raises(InvalidTransitionError):
        transition(TaskState.DELIVERED, TaskEvent.USER_RETRY)


def test_illegal_ignored_resurrection():
    """IGNORED 是终态，无任何回头路（PRD §10）."""
    for ev in TaskEvent:
        with pytest.raises(InvalidTransitionError):
            transition(TaskState.IGNORED, ev)


def test_illegal_suggested_to_doc_generating_directly():
    with pytest.raises(InvalidTransitionError):
        transition(TaskState.SUGGESTED, TaskEvent.PLAN_DONE_DOC)


def test_can_transition_helper():
    assert can_transition(TaskState.SUGGESTED, TaskEvent.USER_CONFIRM)
    assert not can_transition(TaskState.SUGGESTED, TaskEvent.PLAN_DONE_DOC)


def test_legal_events_introspection():
    evs = legal_events(TaskState.SUGGESTED)
    assert TaskEvent.USER_CONFIRM in evs
    assert TaskEvent.USER_IGNORE in evs


# ── Task 实体 ──────────────────────────────────────────────────────────────


def test_task_new_publishes_task_created():
    bus = EventBus()
    received = []
    bus.subscribe(received.append, kind=EVT_TASK_CREATED)
    t = Task.new(intent="下周做活动复盘汇报", owner_open_id="u1", event_bus=bus)
    assert t.state == TaskState.SUGGESTED
    assert t.owner_lock.owner_open_id == "u1"
    assert len(received) == 1
    assert received[0].event_kind == EVT_TASK_CREATED


def test_task_apply_records_transition():
    bus = EventBus()
    t = Task.new(intent="x", owner_open_id="u1", event_bus=bus)
    t.apply(TaskEvent.USER_CONFIRM, actor_open_id="u1", event_bus=bus)
    assert t.state == TaskState.ASSIGNED
    assert len(t.transitions) == 1
    assert t.transitions[0].from_state == "suggested"
    assert t.transitions[0].to_state == "assigned"


def test_task_owner_lock_blocks_non_owner():
    """PRD §6.1 owner 锁: 非 owner 不能推进高影响动作."""
    bus = EventBus()
    t = Task.new(intent="x", owner_open_id="u1", event_bus=bus)
    t.apply(TaskEvent.USER_CONFIRM, actor_open_id="u1", event_bus=bus)
    t.apply(TaskEvent.USER_SKIP_CONTEXT, actor_open_id="u1", event_bus=bus)
    assert t.state == TaskState.PLANNING

    # u2 尝试推进 PLAN_DONE_DOC → 应该被 owner lock 拒绝
    with pytest.raises(OwnerLockedError):
        t.apply(TaskEvent.PLAN_DONE_DOC, actor_open_id="u2", event_bus=bus)


def test_task_assign_changes_owner():
    bus = EventBus()
    received = []
    bus.subscribe(received.append, kind=EVT_TASK_ASSIGNED)
    t = Task.new(intent="x", owner_open_id="u1", event_bus=bus)
    t.assign(to_open_id="u2", by_open_id="u1", event_bus=bus)
    assert t.owner_lock.owner_open_id == "u2"
    assert len(t.owner_lock.history) >= 1
    assert len(received) == 1


def test_task_to_dict_serializable():
    """JSON 持久化：Task.to_dict() 必须可被 json.dumps."""
    import json
    t = Task.new(intent="x", owner_open_id="u1")
    s = json.dumps(t.to_dict(), ensure_ascii=False, default=str)
    assert "task_id" in s
    assert '"state": "suggested"' in s


# ── ContextPack 最小信息闸门 (PRD §5 闸门 3) ───────────────────────────────


def test_context_pack_missing_when_empty():
    cp = ContextPack(task_id="t1", task_goal="", owner_open_id="u1")
    miss = cp.missing()
    assert "task_goal" in miss
    assert "any_material" in miss
    assert not cp.has_min_info()


def test_context_pack_has_min_info_with_messages():
    cp = ContextPack(
        task_id="t1",
        task_goal="活动复盘汇报",
        owner_open_id="u1",
        source_messages=[SourceMessage(sender_open_id="u1", text="消息1")],
        output_requirements=OutputRequirements(primary="ppt", audience="leader"),
    )
    assert cp.has_min_info()


def test_context_pack_total_chars():
    cp = ContextPack(
        task_id="t1",
        task_goal="x",
        owner_open_id="u1",
        source_messages=[SourceMessage(sender_open_id="u", text="abc"),
                         SourceMessage(sender_open_id="u", text="defgh")],
    )
    assert cp.total_chars() == 8


def test_attach_context_marks_confirmed():
    t = Task.new(intent="x", owner_open_id="u1")
    cp = ContextPack(task_id="", task_goal="g", owner_open_id="u1")
    t.attach_context(cp, confirmed=True)
    assert t.context_pack is not None
    assert t.context_pack.confirmed_by_owner
    assert t.context_pack.task_id == t.task_id


# ── Artifact ────────────────────────────────────────────────────────────────


def test_add_artifact_publishes_event():
    bus = EventBus()
    received = []
    bus.subscribe(received.append)
    t = Task.new(intent="x", owner_open_id="u1", event_bus=bus)
    art = Artifact(artifact_id="a1", task_id="", kind=ArtifactKind.DOC,
                    title="复盘文档", feishu_url="https://feishu.cn/doc/xxx")
    t.add_artifact(art, event_bus=bus)
    assert len(t.artifacts) == 1
    assert t.artifacts[0].task_id == t.task_id
    # 至少触发了 task_created + artifact_created
    assert any(e.event_kind == "artifact_created" for e in received)


# ── Event Bus ──────────────────────────────────────────────────────────────


def test_event_bus_kind_filter():
    bus = EventBus()
    all_received = []
    typed_received = []
    bus.subscribe(all_received.append)
    bus.subscribe(typed_received.append, kind=EVT_TASK_STATE_CHANGED)

    bus.publish(make_event(EVT_TASK_CREATED, "t1"))
    bus.publish(make_event(EVT_TASK_STATE_CHANGED, "t1"))
    bus.publish(make_event(EVT_TASK_ASSIGNED, "t1"))

    assert len(all_received) == 3
    assert len(typed_received) == 1


def test_event_bus_subscriber_isolation():
    """单个 subscriber 异常不影响其他人 (PRD-aligned 隔离)."""
    bus = EventBus()
    bad_called = [False]
    good_called = [False]

    def bad(_):
        bad_called[0] = True
        raise RuntimeError("boom")

    def good(_):
        good_called[0] = True

    bus.subscribe(bad)
    bus.subscribe(good)
    bus.publish(make_event("x", "t1"))
    assert bad_called[0]
    assert good_called[0]


def test_event_bus_history_filter():
    bus = EventBus()
    bus.publish(make_event(EVT_TASK_CREATED, "t1"))
    bus.publish(make_event(EVT_TASK_ASSIGNED, "t1"))
    bus.publish(make_event(EVT_TASK_CREATED, "t2"))
    assert len(bus.history(task_id="t1")) == 2
    assert len(bus.history(kind=EVT_TASK_CREATED)) == 2
