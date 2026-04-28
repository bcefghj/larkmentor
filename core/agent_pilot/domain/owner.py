"""Owner 轻量指派与执行锁 (PRD §6 + Q6).

Q6 已结论：**不绑定群角色**（不依赖群主/管理员/项目角色）。
**轻量指派**：谁提出明确需求 → 初始 owner；多人讨论无法判断 → 卡片提示「请选择执行人」。

PRD §6.1 「执行锁定」: 一旦任务进入执行状态，锁定 owner，避免多人重复触发。
PRD §6.4 「阶段 owner」: 文档/PPT/归档可有不同 owner（本实现支持，不强制）。

关键不变量：
1. ``OwnerLock.acquire(actor)`` 当且仅当 actor == owner 时返回 True
2. ``OwnerAssignment`` 持有可选 ``stage`` 字段实现阶段 owner
3. assign / claim / accept / reject 通过 application 层调度，本模块只描述模型
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .errors import OwnerLockedError


@dataclass
class OwnerAssignment:
    """单条指派记录（保留历史）."""

    actor_open_id: str          # 被指派人 open_id
    by_open_id: str             # 指派人 open_id（"" if claim by self）
    accepted: bool = False      # True 表示被指派人已接受
    rejected: bool = False
    stage: Optional[str] = None  # None = 全任务 owner; 否则 "doc"/"ppt"/"canvas"/"archive"
    ts: int = 0                 # epoch seconds


@dataclass
class OwnerLock:
    """锁定结构。锁绑定到 task_id + 当前 owner，防止多人重复执行同一阶段动作."""

    task_id: str
    owner_open_id: str
    locked_action: str = ""     # 当前锁定的高影响动作，如 "doc.create" / "slide.generate"
    locked: bool = False
    history: List[OwnerAssignment] = field(default_factory=list)

    def lock(self, action: str) -> None:
        self.locked_action = action
        self.locked = True

    def unlock(self) -> None:
        self.locked_action = ""
        self.locked = False

    def acquire_for_action(self, actor_open_id: str, action: str) -> None:
        """检查 actor 是否能执行 action；不能则抛 ``OwnerLockedError``."""
        if actor_open_id != self.owner_open_id:
            raise OwnerLockedError(
                task_id=self.task_id,
                owner=self.owner_open_id,
                actor=actor_open_id,
                action=action,
            )
        self.lock(action)

    def transfer_to(self, new_owner_open_id: str, by_open_id: str, *, ts: int) -> None:
        """转交 owner（PRD §6.3 指派流程）。需 application 层在 transfer 前完成 accept 流程."""
        self.history.append(OwnerAssignment(
            actor_open_id=new_owner_open_id,
            by_open_id=by_open_id,
            accepted=True,
            ts=ts,
        ))
        self.owner_open_id = new_owner_open_id
        # 转交时解锁，让新 owner 自行重新 acquire
        self.unlock()


__all__ = ["OwnerAssignment", "OwnerLock"]
