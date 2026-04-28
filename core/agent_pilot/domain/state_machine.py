"""Task 状态机 · PRD §10 完整 10 + 2 状态实现。

状态语义（与 PRD §10 一一对应）：

| State            | PRD 含义                                |
|------------------|----------------------------------------|
| SUGGESTED        | Agent 已识别潜在任务，但未确认           |
| ASSIGNED         | 任务已有 owner，但未开始执行             |
| CONTEXT_PENDING  | 等待补充或确认上下文                    |
| PLANNING         | Agent 正在拆解任务计划                  |
| DOC_GENERATING   | 正在生成文档                            |
| PPT_GENERATING   | 正在生成 PPT/演示稿                     |
| CANVAS_GENERATING| 正在生成自由画布（PRD §15.1 双栈分支）  |
| REVIEWING        | 等待用户检查和修改                      |
| DELIVERED        | 成果已导出或分享                        |
| PAUSED           | 用户暂停                                |
| FAILED           | 任务失败（权限/资料/生成失败）           |
| IGNORED          | 用户忽略建议                            |

事件（驱动转移）：
- 用户事件：confirm / assign / claim / accept / reject / ignore
            add_context / confirm_context / pause / resume / cancel
- 系统事件：context_insufficient / plan_done_doc / plan_done_ppt /
            plan_done_canvas / generation_done / review_complete
            / delivery_done / fatal_error

设计要点：
1. **每条转移显式枚举**——禁止"任意状态都能 fail"这种偷懒
2. **owner check 由 application 层做**——domain 只管转移合法性
3. **transition() 是纯函数**——返回新状态，不修改入参
4. **事件名必须是 ``str``**——便于 JSON 持久化与 hook 系统订阅
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet, Tuple

from .errors import InvalidTransitionError


class TaskState(str, Enum):
    """10 + 2 任务状态（PRD §10）。"""

    SUGGESTED = "suggested"
    ASSIGNED = "assigned"
    CONTEXT_PENDING = "context_pending"
    PLANNING = "planning"
    DOC_GENERATING = "doc_generating"
    PPT_GENERATING = "ppt_generating"
    CANVAS_GENERATING = "canvas_generating"
    REVIEWING = "reviewing"
    DELIVERED = "delivered"
    PAUSED = "paused"
    FAILED = "failed"
    IGNORED = "ignored"

    @property
    def is_terminal(self) -> bool:
        return self in (TaskState.DELIVERED, TaskState.IGNORED, TaskState.FAILED)

    @property
    def is_generating(self) -> bool:
        return self in (
            TaskState.DOC_GENERATING,
            TaskState.PPT_GENERATING,
            TaskState.CANVAS_GENERATING,
        )

    @property
    def is_active(self) -> bool:
        """Active = not terminal and not paused."""
        return not (self.is_terminal or self == TaskState.PAUSED)


class TaskEvent(str, Enum):
    """Driver events for state transitions."""

    # User-driven
    USER_CONFIRM = "user_confirm"
    USER_ASSIGN = "user_assign"
    USER_CLAIM = "user_claim"
    USER_ACCEPT = "user_accept"
    USER_REJECT = "user_reject"
    USER_IGNORE = "user_ignore"
    USER_ADD_CONTEXT = "user_add_context"
    USER_CONFIRM_CONTEXT = "user_confirm_context"
    USER_SKIP_CONTEXT = "user_skip_context"
    USER_PAUSE = "user_pause"
    USER_RESUME = "user_resume"
    USER_CANCEL = "user_cancel"
    USER_REQUEST_PPT = "user_request_ppt"
    USER_REQUEST_CANVAS = "user_request_canvas"
    USER_DELIVER = "user_deliver"
    USER_RETRY = "user_retry"

    # System-driven
    CONTEXT_INSUFFICIENT = "context_insufficient"
    PLAN_DONE_DOC = "plan_done_doc"
    PLAN_DONE_PPT = "plan_done_ppt"
    PLAN_DONE_CANVAS = "plan_done_canvas"
    GENERATION_DONE = "generation_done"
    REVIEW_COMPLETE = "review_complete"
    DELIVERY_DONE = "delivery_done"
    FATAL_ERROR = "fatal_error"


# ── Transition table ────────────────────────────────────────────────────────
# Format: { (from_state, event): to_state }
# Source of truth – any unlisted (state, event) pair is illegal.

_TRANSITIONS: Dict[Tuple[TaskState, TaskEvent], TaskState] = {
    # ── from SUGGESTED ──
    (TaskState.SUGGESTED, TaskEvent.USER_CONFIRM): TaskState.ASSIGNED,
    (TaskState.SUGGESTED, TaskEvent.USER_ASSIGN): TaskState.ASSIGNED,
    (TaskState.SUGGESTED, TaskEvent.USER_CLAIM): TaskState.ASSIGNED,
    (TaskState.SUGGESTED, TaskEvent.USER_IGNORE): TaskState.IGNORED,
    (TaskState.SUGGESTED, TaskEvent.CONTEXT_INSUFFICIENT): TaskState.CONTEXT_PENDING,
    (TaskState.SUGGESTED, TaskEvent.USER_CANCEL): TaskState.IGNORED,

    # ── from ASSIGNED ──
    (TaskState.ASSIGNED, TaskEvent.USER_ADD_CONTEXT): TaskState.CONTEXT_PENDING,
    (TaskState.ASSIGNED, TaskEvent.USER_SKIP_CONTEXT): TaskState.PLANNING,
    (TaskState.ASSIGNED, TaskEvent.USER_CONFIRM_CONTEXT): TaskState.PLANNING,
    (TaskState.ASSIGNED, TaskEvent.USER_ASSIGN): TaskState.ASSIGNED,  # re-assign
    (TaskState.ASSIGNED, TaskEvent.USER_REJECT): TaskState.SUGGESTED,
    (TaskState.ASSIGNED, TaskEvent.USER_PAUSE): TaskState.PAUSED,
    (TaskState.ASSIGNED, TaskEvent.USER_CANCEL): TaskState.IGNORED,
    (TaskState.ASSIGNED, TaskEvent.CONTEXT_INSUFFICIENT): TaskState.CONTEXT_PENDING,

    # ── from CONTEXT_PENDING ──
    (TaskState.CONTEXT_PENDING, TaskEvent.USER_CONFIRM_CONTEXT): TaskState.PLANNING,
    (TaskState.CONTEXT_PENDING, TaskEvent.USER_ADD_CONTEXT): TaskState.CONTEXT_PENDING,
    (TaskState.CONTEXT_PENDING, TaskEvent.USER_PAUSE): TaskState.PAUSED,
    (TaskState.CONTEXT_PENDING, TaskEvent.USER_CANCEL): TaskState.IGNORED,
    (TaskState.CONTEXT_PENDING, TaskEvent.FATAL_ERROR): TaskState.FAILED,

    # ── from PLANNING ──
    (TaskState.PLANNING, TaskEvent.PLAN_DONE_DOC): TaskState.DOC_GENERATING,
    (TaskState.PLANNING, TaskEvent.PLAN_DONE_PPT): TaskState.PPT_GENERATING,
    (TaskState.PLANNING, TaskEvent.PLAN_DONE_CANVAS): TaskState.CANVAS_GENERATING,
    (TaskState.PLANNING, TaskEvent.USER_PAUSE): TaskState.PAUSED,
    (TaskState.PLANNING, TaskEvent.USER_CANCEL): TaskState.IGNORED,
    (TaskState.PLANNING, TaskEvent.FATAL_ERROR): TaskState.FAILED,

    # ── from DOC_GENERATING ──
    (TaskState.DOC_GENERATING, TaskEvent.GENERATION_DONE): TaskState.REVIEWING,
    (TaskState.DOC_GENERATING, TaskEvent.USER_REQUEST_PPT): TaskState.PPT_GENERATING,
    (TaskState.DOC_GENERATING, TaskEvent.USER_REQUEST_CANVAS): TaskState.CANVAS_GENERATING,
    (TaskState.DOC_GENERATING, TaskEvent.USER_PAUSE): TaskState.PAUSED,
    (TaskState.DOC_GENERATING, TaskEvent.FATAL_ERROR): TaskState.FAILED,
    (TaskState.DOC_GENERATING, TaskEvent.USER_CANCEL): TaskState.IGNORED,

    # ── from PPT_GENERATING ──
    (TaskState.PPT_GENERATING, TaskEvent.GENERATION_DONE): TaskState.REVIEWING,
    (TaskState.PPT_GENERATING, TaskEvent.USER_PAUSE): TaskState.PAUSED,
    (TaskState.PPT_GENERATING, TaskEvent.FATAL_ERROR): TaskState.FAILED,
    (TaskState.PPT_GENERATING, TaskEvent.USER_CANCEL): TaskState.IGNORED,

    # ── from CANVAS_GENERATING ──
    (TaskState.CANVAS_GENERATING, TaskEvent.GENERATION_DONE): TaskState.REVIEWING,
    (TaskState.CANVAS_GENERATING, TaskEvent.USER_PAUSE): TaskState.PAUSED,
    (TaskState.CANVAS_GENERATING, TaskEvent.FATAL_ERROR): TaskState.FAILED,
    (TaskState.CANVAS_GENERATING, TaskEvent.USER_CANCEL): TaskState.IGNORED,

    # ── from REVIEWING ──
    (TaskState.REVIEWING, TaskEvent.USER_DELIVER): TaskState.DELIVERED,
    (TaskState.REVIEWING, TaskEvent.USER_REQUEST_PPT): TaskState.PPT_GENERATING,
    (TaskState.REVIEWING, TaskEvent.USER_REQUEST_CANVAS): TaskState.CANVAS_GENERATING,
    (TaskState.REVIEWING, TaskEvent.REVIEW_COMPLETE): TaskState.DELIVERED,
    (TaskState.REVIEWING, TaskEvent.USER_PAUSE): TaskState.PAUSED,
    (TaskState.REVIEWING, TaskEvent.FATAL_ERROR): TaskState.FAILED,
    (TaskState.REVIEWING, TaskEvent.USER_CANCEL): TaskState.IGNORED,

    # ── from PAUSED ──
    (TaskState.PAUSED, TaskEvent.USER_RESUME): TaskState.PLANNING,  # default resume → planning
    (TaskState.PAUSED, TaskEvent.USER_CANCEL): TaskState.IGNORED,
    (TaskState.PAUSED, TaskEvent.FATAL_ERROR): TaskState.FAILED,

    # ── from FAILED ──
    (TaskState.FAILED, TaskEvent.USER_RETRY): TaskState.PLANNING,
    (TaskState.FAILED, TaskEvent.USER_CANCEL): TaskState.IGNORED,

    # IGNORED / DELIVERED are terminal: only reactivate via explicit USER_RETRY (FAILED only)
}


def can_transition(state: TaskState, event: TaskEvent) -> bool:
    """Return True iff (state, event) is a registered legal transition."""
    return (state, event) in _TRANSITIONS


def transition(state: TaskState, event: TaskEvent) -> TaskState:
    """Pure function: given (state, event) return next state.

    Raises ``InvalidTransitionError`` if the transition is not registered.
    The application layer is responsible for owner-lock checks.
    """
    if (state, event) in _TRANSITIONS:
        return _TRANSITIONS[(state, event)]
    raise InvalidTransitionError(
        frm=state.value,
        event=event.value,
        hint=f"legal events from {state.value}: " + ", ".join(
            sorted({ev.value for (s, ev) in _TRANSITIONS if s == state})
        ),
    )


def legal_events(state: TaskState) -> FrozenSet[TaskEvent]:
    """Return the set of legal events from a given state (introspection)."""
    return frozenset(ev for (s, ev) in _TRANSITIONS if s == state)


def transition_count() -> int:
    """Number of registered legal transitions (for documentation/test)."""
    return len(_TRANSITIONS)


__all__ = [
    "TaskState",
    "TaskEvent",
    "transition",
    "can_transition",
    "legal_events",
    "transition_count",
]
