"""Domain layer exceptions.

These are raised by the domain layer; the application layer catches and
translates into user-facing card responses.
"""
from __future__ import annotations


class DomainError(Exception):
    """Base for all domain exceptions."""


class InvalidTransitionError(DomainError):
    """Raised when a state transition is not allowed.

    Carries source/target state for telemetry and card rendering.
    """

    def __init__(self, frm: str, event: str, to: str | None = None, *, hint: str = "") -> None:
        self.frm = frm
        self.event = event
        self.to = to
        self.hint = hint
        msg = f"InvalidTransition: {frm} --[{event}]-> {to or '?'}"
        if hint:
            msg += f" ({hint})"
        super().__init__(msg)


class OwnerLockedError(DomainError):
    """Raised when a non-owner attempts an owner-only action.

    PRD §6.1 「执行锁定」: once a Task enters PLANNING / *_GENERATING,
    only the current owner may transition it forward.
    """

    def __init__(self, *, task_id: str, owner: str, actor: str, action: str) -> None:
        self.task_id = task_id
        self.owner = owner
        self.actor = actor
        self.action = action
        super().__init__(
            f"OwnerLocked: task={task_id} action={action} "
            f"actor={actor} owner={owner}"
        )


class ContextNotReadyError(DomainError):
    """Raised when planner tries to plan without a usable ContextPack.

    PRD §7 「上下文确认」: 不允许直接基于零散聊天生成。
    """

    def __init__(self, *, task_id: str, missing: list[str]) -> None:
        self.task_id = task_id
        self.missing = missing
        super().__init__(
            f"ContextNotReady: task={task_id} missing={missing}"
        )
