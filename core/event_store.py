"""Event Sourcing · 事件溯源持久层.

将 domain EventBus 中所有领域事件持久化到 append-only JSONL 文件，
支持按 task_id 回放、按时间戳查询、实时订阅通知，以及 dashboard 时间线展示。

存储布局::

    data/events/
        2026-05-04.jsonl
        2026-05-05.jsonl
        ...

设计要点：
- 线程安全，写入采用 buffered flush（每 100ms 或 10 条批量刷盘）
- 每日自动切文件，自动清理 30 天前的历史文件
- 零外部依赖，2C2G 服务器友好
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("pilot.event_store")

_DEFAULT_DATA_DIR = os.path.join("data", "events")
_FLUSH_INTERVAL = 0.1  # 100ms
_FLUSH_BATCH_SIZE = 10
_RETENTION_DAYS = 30


class EventStore:
    """Append-only JSONL event store with buffered, thread-safe writes."""

    def __init__(self, data_dir: str | None = None) -> None:
        self._data_dir = Path(data_dir or os.getenv("AGENT_PILOT_EVENTS_DIR", _DEFAULT_DATA_DIR))
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._buffer: List[dict] = []
        self._subscribers: List[Callable[[dict], None]] = []
        self._current_date: str = ""
        self._fh: Any = None

        self._stop_event = threading.Event()
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

        self._cleanup_old_files()

    # ── public API ──────────────────────────────────────────────────────

    def append(self, event: dict) -> None:
        """Persist a single event; triggers subscriber notifications."""
        if "ts" not in event:
            event["ts"] = int(time.time())
        with self._lock:
            self._buffer.append(event)
            if len(self._buffer) >= _FLUSH_BATCH_SIZE:
                self._flush_locked()
        self._notify(event)

    def replay(self, task_id: str) -> List[dict]:
        """Replay all persisted events for *task_id*, oldest first."""
        self._flush()
        events: List[dict] = []
        for path in self._sorted_files():
            for rec in self._iter_file(path):
                if rec.get("task_id") == task_id:
                    events.append(rec)
        return events

    def replay_since(self, ts: int) -> List[dict]:
        """Return all events with ``event['ts'] >= ts``."""
        self._flush()
        start_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        events: List[dict] = []
        for path in self._sorted_files():
            if path.stem < start_date:
                continue
            for rec in self._iter_file(path):
                if rec.get("ts", 0) >= ts:
                    events.append(rec)
        return events

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        """Register *callback* for real-time event notifications."""
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[dict], None]) -> None:
        with self._lock:
            self._subscribers = [s for s in self._subscribers if s is not callback]

    def get_task_timeline(self, task_id: str) -> List[dict]:
        """Chronological timeline for dashboard display.

        Returns simplified dicts::

            [{"ts": 1714900000, "kind": "task_created", "summary": "..."},  ...]
        """
        raw = self.replay(task_id)
        timeline: List[dict] = []
        for ev in raw:
            entry: Dict[str, Any] = {
                "ts": ev.get("ts", 0),
                "kind": ev.get("event_kind", ev.get("kind", "unknown")),
                "actor": ev.get("actor_open_id", ""),
            }
            data = ev.get("data", {})
            if "summary" in data:
                entry["summary"] = data["summary"]
            elif "new_state" in data:
                entry["summary"] = f"State → {data['new_state']}"
            elif "step_name" in data:
                entry["summary"] = data["step_name"]
            else:
                entry["summary"] = entry["kind"].replace("_", " ").title()
            timeline.append(entry)
        return timeline

    def close(self) -> None:
        """Flush remaining buffer and stop the background thread."""
        self._stop_event.set()
        self._flush()
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    # ── internal ────────────────────────────────────────────────────────

    def _notify(self, event: dict) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for fn in subs:
            try:
                fn(event)
            except Exception as e:
                logger.debug("event subscriber callback failed: %s", e)

    def _flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        """Must be called while holding ``self._lock``."""
        if not self._buffer:
            return
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        if today != self._current_date:
            if self._fh is not None:
                self._fh.close()
            filepath = self._data_dir / f"{today}.jsonl"
            self._fh = open(filepath, "a", encoding="utf-8")
            self._current_date = today

        for ev in self._buffer:
            self._fh.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()
        self._buffer.clear()

    def _flush_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=_FLUSH_INTERVAL)
            self._flush()

    def _sorted_files(self) -> List[Path]:
        return sorted(self._data_dir.glob("*.jsonl"), key=lambda p: p.stem)

    @staticmethod
    def _iter_file(path: Path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue
        except FileNotFoundError:
            return

    def _cleanup_old_files(self) -> None:
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=_RETENTION_DAYS)).strftime("%Y-%m-%d")
        for path in self._data_dir.glob("*.jsonl"):
            if path.stem < cutoff:
                try:
                    path.unlink()
                except OSError:
                    pass  # file already removed or locked; skip


# ── singleton ───────────────────────────────────────────────────────────

_default_store: Optional[EventStore] = None
_store_lock = threading.Lock()


def default_event_store() -> EventStore:
    """Module-level singleton, lazy-created."""
    global _default_store
    if _default_store is None:
        with _store_lock:
            if _default_store is None:
                _default_store = EventStore()
    return _default_store


# ── EventBus bridge ────────────────────────────────────────────────────


def attach_to_event_bus(bus: Any | None = None) -> None:
    """Hook into the domain ``EventBus`` to auto-persist all published events.

    If *bus* is ``None`` the default bus from
    ``core.agent_pilot.domain.events`` is used.
    """
    from core.agent_pilot.domain.events import DomainEvent, default_event_bus

    if bus is None:
        bus = default_event_bus()

    store = default_event_store()

    def _persist(event: DomainEvent) -> None:
        store.append(event.to_dict())

    bus.subscribe(_persist)


__all__ = [
    "EventStore",
    "default_event_store",
    "attach_to_event_bus",
]
