"""Domain events · 领域事件总线.

设计要点：
1. 事件是不可变 dataclass，JSON 可序列化
2. EventBus 是同步 + 线程安全；多 agent 协同时各 subscriber 串行触发
3. ``default_event_bus()`` 单例。Application 层在 task_service 中 publish；
   下游订阅者：sync hub、audit log、learner 学习闭环、dashboard SSE
4. 不引入 redis/kafka，2C2G 服务器友好
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class DomainEvent:
    """领域事件不可变基础结构."""

    event_kind: str             # "task_created" / "task_assigned" / "task_state_changed" / ...
    task_id: str
    actor_open_id: str = ""     # 触发事件的 user (空 = 系统触发)
    data: Dict[str, Any] = field(default_factory=dict)
    ts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


Subscriber = Callable[[DomainEvent], None]


class EventBus:
    """同步事件总线（线程安全）."""

    def __init__(self) -> None:
        self._subs: List[Subscriber] = []
        self._kind_subs: Dict[str, List[Subscriber]] = {}
        self._lock = threading.Lock()
        self._history: List[DomainEvent] = []  # for replay / debug

    def subscribe(self, fn: Subscriber, *, kind: Optional[str] = None) -> None:
        """订阅。``kind=None`` 表示订阅所有事件。"""
        with self._lock:
            if kind is None:
                self._subs.append(fn)
            else:
                self._kind_subs.setdefault(kind, []).append(fn)

    def unsubscribe(self, fn: Subscriber) -> None:
        with self._lock:
            self._subs = [s for s in self._subs if s is not fn]
            for kind, lst in list(self._kind_subs.items()):
                self._kind_subs[kind] = [s for s in lst if s is not fn]

    def publish(self, event: DomainEvent) -> None:
        """发布事件；订阅者串行触发，单个 subscriber 异常不影响其他人."""
        with self._lock:
            self._history.append(event)
            subs = list(self._subs)
            kind_subs = list(self._kind_subs.get(event.event_kind, []))
        for fn in subs + kind_subs:
            try:
                fn(event)
            except Exception:
                # subscriber 内部错误隔离；audit_log 自身也有异常处理
                pass

    def history(self, *, task_id: Optional[str] = None, kind: Optional[str] = None,
                limit: int = 100) -> List[DomainEvent]:
        with self._lock:
            evs = list(self._history)
        if task_id:
            evs = [e for e in evs if e.task_id == task_id]
        if kind:
            evs = [e for e in evs if e.event_kind == kind]
        return evs[-limit:]


_default_bus: Optional[EventBus] = None


def default_event_bus() -> EventBus:
    global _default_bus
    if _default_bus is None:
        _default_bus = EventBus()
    return _default_bus


# ── 事件 kind 常量（避免拼写错误）─────────────────────────────────────────────
EVT_TASK_CREATED = "task_created"
EVT_TASK_STATE_CHANGED = "task_state_changed"
EVT_TASK_ASSIGNED = "task_assigned"
EVT_TASK_REJECTED = "task_rejected"
EVT_TASK_OWNER_LOCKED = "task_owner_locked"
EVT_CONTEXT_CONFIRMED = "context_confirmed"
EVT_PLAN_CREATED = "plan_created"
EVT_STEP_STARTED = "step_started"
EVT_STEP_DONE = "step_done"
EVT_STEP_FAILED = "step_failed"
EVT_ARTIFACT_CREATED = "artifact_created"
EVT_TASK_DELIVERED = "task_delivered"
EVT_TASK_FAILED = "task_failed"
EVT_TASK_IGNORED = "task_ignored"


def make_event(kind: str, task_id: str, *, actor_open_id: str = "",
               data: Optional[Dict[str, Any]] = None,
               ts: Optional[int] = None) -> DomainEvent:
    return DomainEvent(
        event_kind=kind,
        task_id=task_id,
        actor_open_id=actor_open_id,
        data=data or {},
        ts=ts or int(time.time()),
    )


__all__ = [
    "DomainEvent",
    "EventBus",
    "Subscriber",
    "default_event_bus",
    "make_event",
    "EVT_TASK_CREATED",
    "EVT_TASK_STATE_CHANGED",
    "EVT_TASK_ASSIGNED",
    "EVT_TASK_REJECTED",
    "EVT_TASK_OWNER_LOCKED",
    "EVT_CONTEXT_CONFIRMED",
    "EVT_PLAN_CREATED",
    "EVT_STEP_STARTED",
    "EVT_STEP_DONE",
    "EVT_STEP_FAILED",
    "EVT_ARTIFACT_CREATED",
    "EVT_TASK_DELIVERED",
    "EVT_TASK_FAILED",
    "EVT_TASK_IGNORED",
]
