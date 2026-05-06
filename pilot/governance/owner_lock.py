"""Owner Lock — PRD §6.3 任务执行锁定 + §问题 6 轻量指派.

任务进入执行后:
  - 当前 owner 单独持有"推进"权限（同阶段同动作不可重复触发）
  - 其他成员可申请接管（claim）→ 当前 owner 同意后转交
  - 管理员（可选）强制接管
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OwnerLock:
    task_id: str
    owner_open_id: str
    locked: bool = False
    locked_at: int = 0
    pending_claims: list[str] = field(default_factory=list)  # 申请接管列表

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "owner_open_id": self.owner_open_id,
            "locked": self.locked,
            "locked_at": self.locked_at,
            "pending_claims": self.pending_claims,
        }


class OwnerLockStore:
    """轻量内存锁；生产可换 Redis."""

    def __init__(self) -> None:
        self._locks: dict[str, OwnerLock] = {}
        self._mutex = threading.Lock()

    def create(self, *, task_id: str, owner_open_id: str) -> OwnerLock:
        with self._mutex:
            lock = OwnerLock(task_id=task_id, owner_open_id=owner_open_id)
            self._locks[task_id] = lock
            return lock

    def get(self, task_id: str) -> OwnerLock | None:
        return self._locks.get(task_id)

    def lock_for_execution(self, task_id: str) -> bool:
        """切到执行状态时锁定。已锁定返回 False。"""
        with self._mutex:
            lock = self._locks.get(task_id)
            if not lock:
                return False
            if lock.locked:
                return False
            lock.locked = True
            lock.locked_at = int(time.time())
            return True

    def is_locked(self, task_id: str) -> bool:
        lock = self._locks.get(task_id)
        return bool(lock and lock.locked)

    def can_perform(self, *, task_id: str, actor_open_id: str) -> bool:
        """actor 是否能在该任务上执行"推进"动作？"""
        lock = self._locks.get(task_id)
        if not lock:
            return False
        if not lock.locked:
            # 未锁定，谁先来谁推进
            return True
        return lock.owner_open_id == actor_open_id

    def request_claim(self, *, task_id: str, claimant: str) -> bool:
        with self._mutex:
            lock = self._locks.get(task_id)
            if not lock:
                return False
            if claimant != lock.owner_open_id and claimant not in lock.pending_claims:
                lock.pending_claims.append(claimant)
            return True

    def transfer(self, *, task_id: str, from_open_id: str, to_open_id: str) -> bool:
        """当前 owner 同意转交."""
        with self._mutex:
            lock = self._locks.get(task_id)
            if not lock:
                return False
            if lock.owner_open_id != from_open_id:
                return False
            lock.owner_open_id = to_open_id
            if to_open_id in lock.pending_claims:
                lock.pending_claims.remove(to_open_id)
            return True

    def unlock(self, task_id: str) -> None:
        with self._mutex:
            lock = self._locks.get(task_id)
            if lock:
                lock.locked = False


_default: OwnerLockStore | None = None


def default_lock_store() -> OwnerLockStore:
    global _default
    if _default is None:
        _default = OwnerLockStore()
    return _default
