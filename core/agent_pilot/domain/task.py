"""Task entity · PRD §6 + §10 完整模型.

Task 是 Pilot 主流程的核心聚合根（aggregate root），持有：
- 状态（来自 ``state_machine.TaskState``）
- owner 锁 (``owner.OwnerLock``)
- 上下文包 (``context_pack.ContextPack``，可空直到 PLANNING）
- DAG plan (``plan.Plan``，可空直到 PLANNING）
- 产出物列表 (``artifact.Artifact``)
- agent 日志（推理痕迹，PRD §8.1 「Agent 日志」可视化）
- 转移历史

Task 是 application 层 ``task_service`` 的主要操作对象。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .artifact import Artifact
from .context_pack import ContextPack
from .errors import InvalidTransitionError, OwnerLockedError
from .events import DomainEvent, EventBus, default_event_bus, make_event
from .events import (
    EVT_TASK_CREATED,
    EVT_TASK_STATE_CHANGED,
    EVT_TASK_ASSIGNED,
    EVT_TASK_OWNER_LOCKED,
    EVT_CONTEXT_CONFIRMED,
    EVT_ARTIFACT_CREATED,
)
from .owner import OwnerAssignment, OwnerLock
from .plan import Plan
from .state_machine import TaskEvent, TaskState, transition


@dataclass
class TransitionRecord:
    """每次状态转移的留痕."""

    from_state: str
    to_state: str
    event: str
    actor_open_id: str = ""
    ts: int = 0
    note: str = ""


@dataclass
class AgentLogEntry:
    """Agent 推理痕迹一条（PRD §8.1）."""

    agent: str           # "@pilot" / "@researcher" / "@validator" / ...
    kind: str            # "thought" / "tool_call" / "result" / "error" / "delegation"
    content: str
    ts: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Task:
    """聚合根·任务实体."""

    task_id: str
    title: str = ""
    intent: str = ""                        # 用户原始自然语言或 IM 摘要
    source_chat_id: str = ""
    source_msg_id: str = ""
    tenant_id: str = "default"
    workspace_id: str = ""                  # 6 级 Memory 之一
    department_id: str = ""
    state: TaskState = TaskState.SUGGESTED

    # owner / lock
    owner_lock: OwnerLock = field(default_factory=lambda: OwnerLock(task_id="", owner_open_id=""))

    # context / plan / artifacts
    context_pack: Optional[ContextPack] = None
    plan: Optional[Plan] = None
    artifacts: List[Artifact] = field(default_factory=list)

    # logs
    transitions: List[TransitionRecord] = field(default_factory=list)
    agent_logs: List[AgentLogEntry] = field(default_factory=list)

    # timestamps
    created_ts: int = 0
    updated_ts: int = 0

    # ── factories ─────────────────────────────────────────────────────────────
    @classmethod
    def new(cls, *, intent: str, source_chat_id: str = "",
            source_msg_id: str = "", tenant_id: str = "default",
            workspace_id: str = "", department_id: str = "",
            owner_open_id: str = "",
            title: str = "", task_id: str = "",
            event_bus: Optional[EventBus] = None) -> "Task":
        tid = task_id or f"task-{uuid.uuid4().hex[:10]}"
        now = int(time.time())
        t = cls(
            task_id=tid,
            title=title or intent[:50],
            intent=intent,
            source_chat_id=source_chat_id,
            source_msg_id=source_msg_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            department_id=department_id,
            state=TaskState.SUGGESTED,
            owner_lock=OwnerLock(task_id=tid, owner_open_id=owner_open_id),
            created_ts=now,
            updated_ts=now,
        )
        bus = event_bus or default_event_bus()
        bus.publish(make_event(
            EVT_TASK_CREATED, tid,
            actor_open_id=owner_open_id,
            data={"intent": intent[:200], "title": t.title},
            ts=now,
        ))
        return t

    # ── transitions ───────────────────────────────────────────────────────────
    def apply(self, event: TaskEvent, *, actor_open_id: str = "",
              note: str = "", event_bus: Optional[EventBus] = None,
              enforce_owner_lock: bool = True) -> None:
        """触发一次状态转移.

        Args:
            event: 事件枚举
            actor_open_id: 触发动作的用户 open_id
            note: 备注（自由文本）
            event_bus: 自定义 bus（默认 default）
            enforce_owner_lock: 当 state 是"已锁定阶段"时校验 actor==owner

        Raises:
            InvalidTransitionError: 转移非法
            OwnerLockedError: actor 不是 owner 但试图执行 owner-only 动作
        """
        bus = event_bus or default_event_bus()
        old = self.state

        # owner lock 检查（PRD §6.1 执行锁定）
        if enforce_owner_lock and self.owner_lock.owner_open_id and actor_open_id:
            if old.is_generating or old in (TaskState.PLANNING, TaskState.REVIEWING):
                if actor_open_id != self.owner_lock.owner_open_id:
                    # 仅当事件是"高影响动作"时才严格检查
                    if event in (
                        TaskEvent.PLAN_DONE_DOC,
                        TaskEvent.PLAN_DONE_PPT,
                        TaskEvent.PLAN_DONE_CANVAS,
                        TaskEvent.GENERATION_DONE,
                        TaskEvent.USER_DELIVER,
                        TaskEvent.REVIEW_COMPLETE,
                    ):
                        raise OwnerLockedError(
                            task_id=self.task_id,
                            owner=self.owner_lock.owner_open_id,
                            actor=actor_open_id,
                            action=event.value,
                        )

        new = transition(old, event)
        ts = int(time.time())
        self.state = new
        self.updated_ts = ts
        self.transitions.append(TransitionRecord(
            from_state=old.value, to_state=new.value, event=event.value,
            actor_open_id=actor_open_id, ts=ts, note=note,
        ))
        bus.publish(make_event(
            EVT_TASK_STATE_CHANGED, self.task_id,
            actor_open_id=actor_open_id,
            data={"from": old.value, "to": new.value, "event": event.value, "note": note},
            ts=ts,
        ))

    # ── owner ops ─────────────────────────────────────────────────────────────
    def assign(self, *, to_open_id: str, by_open_id: str,
               event_bus: Optional[EventBus] = None) -> None:
        bus = event_bus or default_event_bus()
        ts = int(time.time())
        if not self.owner_lock.owner_open_id:
            self.owner_lock.owner_open_id = to_open_id
            self.owner_lock.history.append(OwnerAssignment(
                actor_open_id=to_open_id, by_open_id=by_open_id,
                accepted=True, ts=ts,
            ))
        else:
            self.owner_lock.transfer_to(to_open_id, by_open_id, ts=ts)
        self.updated_ts = ts
        bus.publish(make_event(
            EVT_TASK_ASSIGNED, self.task_id,
            actor_open_id=by_open_id,
            data={"to": to_open_id, "by": by_open_id},
            ts=ts,
        ))

    def lock_for_action(self, *, actor_open_id: str, action: str,
                        event_bus: Optional[EventBus] = None) -> None:
        self.owner_lock.acquire_for_action(actor_open_id, action)
        bus = event_bus or default_event_bus()
        bus.publish(make_event(
            EVT_TASK_OWNER_LOCKED, self.task_id,
            actor_open_id=actor_open_id,
            data={"action": action, "owner": self.owner_lock.owner_open_id},
        ))

    # ── context ──────────────────────────────────────────────────────────────
    def attach_context(self, ctx: ContextPack, *, confirmed: bool = False,
                        event_bus: Optional[EventBus] = None) -> None:
        ctx.task_id = self.task_id
        if confirmed and not ctx.confirmed_by_owner:
            ctx.confirmed_by_owner = True
            ctx.confirm_ts = int(time.time())
        self.context_pack = ctx
        self.updated_ts = int(time.time())
        if confirmed:
            (event_bus or default_event_bus()).publish(make_event(
                EVT_CONTEXT_CONFIRMED, self.task_id,
                actor_open_id=self.owner_lock.owner_open_id,
                data={"goal": ctx.task_goal[:200], "n_msgs": len(ctx.source_messages)},
            ))

    # ── artifacts ─────────────────────────────────────────────────────────────
    def add_artifact(self, art: Artifact, *, event_bus: Optional[EventBus] = None) -> None:
        art.task_id = self.task_id
        if not art.created_ts:
            art.created_ts = int(time.time())
        self.artifacts.append(art)
        self.updated_ts = int(time.time())
        (event_bus or default_event_bus()).publish(make_event(
            EVT_ARTIFACT_CREATED, self.task_id,
            data={"artifact_id": art.artifact_id, "kind": art.kind.value,
                  "title": art.title[:120]},
        ))

    # ── agent log ────────────────────────────────────────────────────────────
    def log(self, *, agent: str, kind: str, content: str,
            meta: Optional[Dict[str, Any]] = None) -> None:
        self.agent_logs.append(AgentLogEntry(
            agent=agent, kind=kind, content=content,
            ts=int(time.time()), meta=meta or {},
        ))
        self.updated_ts = int(time.time())

    # ── serialization ─────────────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Enum -> str
        d["state"] = self.state.value
        return d


__all__ = ["Task", "TransitionRecord", "AgentLogEntry"]
