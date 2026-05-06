"""Task state machine – PRD §10 落地.

10 explicit states with allowed transitions. Each plan stores its task state
under ``data/pilot_tasks/{plan_id}.json`` so the dashboard / Flutter clients
can subscribe.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("agent_pilot.runtime.state_machine")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TASK_DIR = PROJECT_ROOT / "data" / "pilot_tasks"


class TaskState(str, Enum):
    SUGGESTED = "suggested"           # Agent 已识别但未确认
    ASSIGNED = "assigned"             # 已有 owner，未开始执行
    CONTEXT_PENDING = "context_pending"  # 等待补充/确认上下文
    PLANNING = "planning"             # 规划中
    DOC_GENERATING = "doc_generating"
    PPT_GENERATING = "ppt_generating"
    REVIEWING = "reviewing"           # 等待用户检查
    DELIVERED = "delivered"
    PAUSED = "paused"
    FAILED = "failed"
    IGNORED = "ignored"


_TRANSITIONS: Dict[TaskState, Set[TaskState]] = {
    TaskState.SUGGESTED: {TaskState.ASSIGNED, TaskState.IGNORED, TaskState.CONTEXT_PENDING, TaskState.PLANNING},
    TaskState.ASSIGNED: {TaskState.CONTEXT_PENDING, TaskState.PLANNING, TaskState.PAUSED, TaskState.IGNORED},
    TaskState.CONTEXT_PENDING: {TaskState.PLANNING, TaskState.PAUSED, TaskState.IGNORED},
    TaskState.PLANNING: {TaskState.DOC_GENERATING, TaskState.PPT_GENERATING, TaskState.REVIEWING, TaskState.FAILED, TaskState.PAUSED},
    TaskState.DOC_GENERATING: {TaskState.PPT_GENERATING, TaskState.REVIEWING, TaskState.FAILED, TaskState.PAUSED},
    TaskState.PPT_GENERATING: {TaskState.REVIEWING, TaskState.FAILED, TaskState.PAUSED},
    TaskState.REVIEWING: {TaskState.DELIVERED, TaskState.DOC_GENERATING, TaskState.PPT_GENERATING, TaskState.PAUSED, TaskState.FAILED},
    TaskState.DELIVERED: {TaskState.REVIEWING},  # allow re-iteration
    TaskState.PAUSED: {TaskState.PLANNING, TaskState.DOC_GENERATING, TaskState.PPT_GENERATING, TaskState.IGNORED},
    TaskState.FAILED: {TaskState.PLANNING, TaskState.IGNORED},
    TaskState.IGNORED: {TaskState.SUGGESTED},
}


@dataclass
class TaskRecord:
    plan_id: str
    intent: str
    owner_open_id: str = ""
    requested_by: str = ""
    state: str = TaskState.SUGGESTED.value
    chat_id: str = ""
    chat_type: str = "p2p"
    created_ts: int = 0
    updated_ts: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)
    locks: Dict[str, str] = field(default_factory=dict)  # action_name -> locked_ts
    artifacts: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _path(plan_id: str) -> Path:
    return TASK_DIR / f"{plan_id}.json"


def create_task(
    plan_id: str,
    intent: str,
    *,
    requested_by: str = "",
    owner_open_id: str = "",
    chat_id: str = "",
    chat_type: str = "p2p",
    initial_state: TaskState = TaskState.SUGGESTED,
) -> TaskRecord:
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    rec = TaskRecord(
        plan_id=plan_id,
        intent=intent,
        owner_open_id=owner_open_id or requested_by,
        requested_by=requested_by,
        state=initial_state.value,
        chat_id=chat_id,
        chat_type=chat_type,
        created_ts=int(time.time()),
        updated_ts=int(time.time()),
        history=[{
            "ts": int(time.time()),
            "from_state": "",
            "to_state": initial_state.value,
            "reason": "task_created",
            "actor": requested_by,
        }],
    )
    _save(rec)
    return rec


def transition(
    plan_id: str,
    new_state: TaskState,
    *,
    actor: str = "",
    reason: str = "",
) -> Optional[TaskRecord]:
    rec = load(plan_id)
    if rec is None:
        logger.warning("transition: task %s not found", plan_id)
        return None
    cur = TaskState(rec.state)
    allowed = _TRANSITIONS.get(cur, set())
    if new_state not in allowed:
        logger.warning("transition: %s → %s not allowed (allowed: %s)",
                       cur.value, new_state.value, [s.value for s in allowed])
        return None
    rec.history.append({
        "ts": int(time.time()),
        "from_state": cur.value,
        "to_state": new_state.value,
        "reason": reason,
        "actor": actor,
    })
    rec.state = new_state.value
    rec.updated_ts = int(time.time())
    _save(rec)
    return rec


def assign_owner(plan_id: str, new_owner: str, *, actor: str = "") -> Optional[TaskRecord]:
    rec = load(plan_id)
    if rec is None:
        return None
    rec.history.append({
        "ts": int(time.time()),
        "from_state": rec.state,
        "to_state": rec.state,
        "reason": f"owner_change: {rec.owner_open_id} → {new_owner}",
        "actor": actor or rec.owner_open_id,
    })
    rec.owner_open_id = new_owner
    rec.updated_ts = int(time.time())
    _save(rec)
    return rec


def lock_action(plan_id: str, action: str) -> bool:
    rec = load(plan_id)
    if rec is None:
        return False
    if action in rec.locks:
        return False  # already locked
    rec.locks[action] = str(int(time.time()))
    rec.updated_ts = int(time.time())
    _save(rec)
    return True


def unlock_action(plan_id: str, action: str) -> None:
    rec = load(plan_id)
    if rec is None:
        return
    rec.locks.pop(action, None)
    rec.updated_ts = int(time.time())
    _save(rec)


def attach_artifact(plan_id: str, key: str, url: str) -> None:
    rec = load(plan_id)
    if rec is None:
        return
    rec.artifacts[key] = url
    rec.updated_ts = int(time.time())
    _save(rec)


def load(plan_id: str) -> Optional[TaskRecord]:
    p = _path(plan_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return TaskRecord(**data)
    except Exception as e:
        logger.warning("load task %s failed: %s", plan_id, e)
        return None


def _save(rec: TaskRecord) -> None:
    p = _path(rec.plan_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec.to_dict(), ensure_ascii=False, indent=2),
                 encoding="utf-8")


__all__ = [
    "TaskState",
    "TaskRecord",
    "create_task",
    "transition",
    "assign_owner",
    "lock_action",
    "unlock_action",
    "attach_artifact",
    "load",
]
