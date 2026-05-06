"""V1.5 — Task 状态机合法/非法转移 + stage_owners 测试."""

from __future__ import annotations

import pytest

from pilot.runtime.session import (
    STAGES,
    IllegalTransitionError,
    Task,
    TaskState,
)


def _new_task(state: TaskState = TaskState.SUGGESTED) -> Task:
    t = Task(intent="x")
    t.state = state
    return t


def test_initial_state_is_suggested() -> None:
    assert Task(intent="x").state == TaskState.SUGGESTED


def test_legal_path_full_journey() -> None:
    t = _new_task()
    for s in (
        TaskState.ASSIGNED,
        TaskState.CONTEXT_PENDING,
        TaskState.PLANNING,
        TaskState.DOC_GENERATING,
        TaskState.PPT_GENERATING,
        TaskState.REVIEWING,
        TaskState.DELIVERED,
    ):
        t.transition_to(s)
        assert t.state == s


def test_illegal_skip_to_delivered_raises() -> None:
    t = _new_task()
    with pytest.raises(IllegalTransitionError):
        t.transition_to(TaskState.DELIVERED)


def test_illegal_skip_planning_to_ppt_directly_is_legal() -> None:
    """PLANNING → PPT_GENERATING 是合法（短路径，仅 PPT 任务）."""
    t = _new_task(TaskState.PLANNING)
    t.transition_to(TaskState.PPT_GENERATING)
    assert t.state == TaskState.PPT_GENERATING


def test_paused_can_resume_to_planning_or_doc() -> None:
    t = _new_task(TaskState.PAUSED)
    t.transition_to(TaskState.PLANNING)
    t = _new_task(TaskState.PAUSED)
    t.transition_to(TaskState.DOC_GENERATING)


def test_failed_can_retry_to_planning() -> None:
    t = _new_task(TaskState.FAILED)
    t.transition_to(TaskState.PLANNING)
    assert t.state == TaskState.PLANNING


def test_force_bypass_legal_check() -> None:
    t = _new_task()
    t.transition(TaskState.DELIVERED, force=True)
    assert t.state == TaskState.DELIVERED


def test_can_transition_to() -> None:
    t = _new_task(TaskState.PLANNING)
    assert t.can_transition_to(TaskState.DOC_GENERATING)
    assert not t.can_transition_to(TaskState.SUGGESTED)


def test_same_state_idempotent() -> None:
    t = _new_task(TaskState.PLANNING)
    t.transition_to(TaskState.PLANNING)
    assert t.state == TaskState.PLANNING


def test_stage_owners_only_known_stages() -> None:
    t = _new_task()
    for stage in STAGES:
        t.set_stage_owner(stage, f"ou_{stage}")
        assert t.stage_owners[stage] == f"ou_{stage}"

    with pytest.raises(ValueError):
        t.set_stage_owner("unknown_stage", "ou_x")


def test_ignored_can_revive_to_suggested() -> None:
    t = _new_task(TaskState.IGNORED)
    t.transition_to(TaskState.SUGGESTED)
    assert t.state == TaskState.SUGGESTED


def test_delivered_can_loop_back_to_reviewing() -> None:
    t = _new_task(TaskState.DELIVERED)
    t.transition_to(TaskState.REVIEWING)
    assert t.state == TaskState.REVIEWING
