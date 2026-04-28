"""TaskService · 任务用例编排（PRD §6 §10）.

application 层的核心入口——所有 Bot/Card/Dashboard 调用都通过本服务推进
任务，从而保证：
1. 状态转移 + owner 锁 + Domain Event 发布全程统一处理
2. JSON 持久化（``repository``）
3. 可被多 agent 工具调用（``..reasoning`` 模块）

设计选择：
- 同步实现，2C2G 友好（不引入 asyncio 在主路径）
- ``default_task_service()`` 单例
- 持久化目录默认 ``data/tasks/``，由调用方覆盖
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..domain import (
    Artifact,
    ContextPack,
    EventBus,
    Task,
    TaskEvent,
    TaskState,
    default_event_bus,
)

logger = logging.getLogger("pilot.application.task_service")


class TaskRepository:
    """JSON 文件仓储（无依赖）."""

    def __init__(self, root: str = "data/tasks") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cache: Dict[str, Task] = {}

    def _path(self, task_id: str) -> Path:
        return self.root / f"{task_id}.json"

    def save(self, t: Task) -> None:
        p = self._path(t.task_id)
        with self._lock:
            self._cache[t.task_id] = t
            try:
                p.write_text(
                    json.dumps(t.to_dict(), ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
            except Exception:
                logger.exception("save task %s failed", t.task_id)

    def load(self, task_id: str) -> Optional[Task]:
        with self._lock:
            if task_id in self._cache:
                return self._cache[task_id]
        p = self._path(task_id)
        if not p.exists():
            return None
        # NOTE: a full deserializer (turning dict back to Task) is intentionally
        # skipped here because TaskService keeps live tasks in-memory; the
        # JSON files exist for inspection / dashboard / cold start.
        # Cold-start rehydrate is a P10 dashboard concern, not P2.
        return None

    def list(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        files = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        out: List[Dict[str, Any]] = []
        for f in files[:limit]:
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue
        return out


class TaskService:
    """任务服务 facade."""

    def __init__(self, *, repository: Optional[TaskRepository] = None,
                 event_bus: Optional[EventBus] = None) -> None:
        self.repo = repository or TaskRepository()
        self.bus = event_bus or default_event_bus()
        self._live: Dict[str, Task] = {}
        self._lock = threading.Lock()

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def create_task(self, *, intent: str, owner_open_id: str = "",
                    source_chat_id: str = "", source_msg_id: str = "",
                    tenant_id: str = "default", workspace_id: str = "",
                    department_id: str = "", title: str = "") -> Task:
        t = Task.new(
            intent=intent,
            owner_open_id=owner_open_id,
            source_chat_id=source_chat_id,
            source_msg_id=source_msg_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            department_id=department_id,
            title=title,
            event_bus=self.bus,
        )
        with self._lock:
            self._live[t.task_id] = t
        self.repo.save(t)
        return t

    def get(self, task_id: str) -> Optional[Task]:
        with self._lock:
            return self._live.get(task_id)

    def list_live(self) -> List[Task]:
        with self._lock:
            return list(self._live.values())

    # ── state transitions ─────────────────────────────────────────────────────
    def fire(self, task_id: str, event: TaskEvent, *,
             actor_open_id: str = "", note: str = "",
             enforce_owner_lock: bool = True) -> Task:
        t = self.get(task_id)
        if t is None:
            raise KeyError(f"task not found: {task_id}")
        t.apply(event, actor_open_id=actor_open_id, note=note,
                event_bus=self.bus, enforce_owner_lock=enforce_owner_lock)
        self.repo.save(t)
        return t

    # ── owner ops ─────────────────────────────────────────────────────────────
    def assign(self, task_id: str, *, to_open_id: str, by_open_id: str) -> Task:
        t = self.get(task_id)
        if t is None:
            raise KeyError(f"task not found: {task_id}")
        t.assign(to_open_id=to_open_id, by_open_id=by_open_id, event_bus=self.bus)
        self.repo.save(t)
        return t

    def claim(self, task_id: str, *, by_open_id: str) -> Task:
        """非 owner 主动认领（PRD §6.1 「我来执行」）."""
        return self.assign(task_id, to_open_id=by_open_id, by_open_id=by_open_id)

    # ── context ──────────────────────────────────────────────────────────────
    def attach_context(self, task_id: str, ctx: ContextPack, *,
                       confirmed: bool = False) -> Task:
        t = self.get(task_id)
        if t is None:
            raise KeyError(f"task not found: {task_id}")
        t.attach_context(ctx, confirmed=confirmed, event_bus=self.bus)
        self.repo.save(t)
        return t

    # ── artifacts ─────────────────────────────────────────────────────────────
    def add_artifact(self, task_id: str, artifact: Artifact) -> Task:
        t = self.get(task_id)
        if t is None:
            raise KeyError(f"task not found: {task_id}")
        t.add_artifact(artifact, event_bus=self.bus)
        self.repo.save(t)
        return t

    # ── stats / dashboard helpers ─────────────────────────────────────────────
    def stats(self) -> Dict[str, int]:
        with self._lock:
            d: Dict[str, int] = {}
            for t in self._live.values():
                d[t.state.value] = d.get(t.state.value, 0) + 1
            d["total"] = len(self._live)
            return d


_default_service: Optional[TaskService] = None


def default_task_service() -> TaskService:
    global _default_service
    if _default_service is None:
        root = os.getenv("PILOT_TASK_ROOT", "data/tasks")
        _default_service = TaskService(repository=TaskRepository(root))
    return _default_service


__all__ = ["TaskService", "TaskRepository", "default_task_service"]
