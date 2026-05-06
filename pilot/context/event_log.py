"""append-only 事件日志.

每个 session 一个 events.jsonl，所有事件按时间顺序追加；不可修改、不可删除。
便于：
  - replay：重放任意一段历史
  - debug：精确定位故障点
  - audit：满足 PRD §6.3 owner_lock 审计需求
  - context reset：用结构化 handoff artifact 交接
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger("pilot.context.event_log")

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data"))).resolve()
EVENTS_DIR = DATA_DIR / "events"


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


class EventLog:
    """每个 session 一个 EventLog 实例."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.path = _ensure(EVENTS_DIR / session_id) / "events.jsonl"
        self._lock = asyncio.Lock()

    async def append(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        evt = {
            "ts": time.time(),
            "kind": kind,
            "payload": payload,
        }
        async with self._lock:
            try:
                with self.path.open("a", encoding="utf-8") as fp:
                    fp.write(json.dumps(evt, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.warning("event_log append failed: %s", e)
        return evt

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        except Exception as e:
            logger.warning("event_log read failed: %s", e)
        return out

    def read_kind(self, kinds: Iterable[str]) -> list[dict[str, Any]]:
        kinds_set = set(kinds)
        return [e for e in self.read_all() if e.get("kind") in kinds_set]

    def tail(self, n: int = 50) -> list[dict[str, Any]]:
        all_evts = self.read_all()
        return all_evts[-n:]


def list_sessions(limit: int = 50) -> list[str]:
    """列出最近 N 个 session_id."""
    if not EVENTS_DIR.exists():
        return []
    return [p.name for p in sorted(EVENTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]]
