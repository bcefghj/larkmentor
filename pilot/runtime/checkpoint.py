"""Session 检查点（落盘 + 恢复）.

V1 用最简文件系统 checkpoint，避免引入 LangGraph SQLite 复杂度；
未来可平滑迁移到 LangGraph SqliteCheckpointer/PostgresCheckpointer。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from pilot.runtime.session import Session, Step, Task

logger = logging.getLogger("pilot.runtime.checkpoint")

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data"))).resolve()


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def session_path(session_id: str) -> Path:
    return _ensure(DATA_DIR / "sessions" / session_id)


def save_session(session: Session) -> Path:
    """落盘 session 主体."""
    p = session_path(session.session_id)
    f = p / "session.json"
    f.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    logger.debug("checkpoint.session %s", session.session_id)
    return f


def save_task(task: Task) -> Path:
    p = session_path(task.session_id) if task.session_id else _ensure(DATA_DIR / "tasks")
    f = p / f"task_{task.task_id}.json"
    f.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return f


def append_step(step: Step) -> Path:
    """append-only：落到 session 目录下 steps.jsonl."""
    p = session_path(step.session_id) if step.session_id else _ensure(DATA_DIR / "steps")
    f = p / "steps.jsonl"
    with f.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(step.to_dict(), ensure_ascii=False) + "\n")
    return f


def load_session(session_id: str) -> dict[str, Any] | None:
    f = session_path(session_id) / "session.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("load_session failed: %s", e)
        return None


def list_sessions(limit: int = 50) -> list[dict[str, Any]]:
    """列出最近 N 个 session（按 mtime 倒序）."""
    base = DATA_DIR / "sessions"
    if not base.exists():
        return []
    items = []
    for sd in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        sf = sd / "session.json"
        if sf.exists():
            try:
                items.append(json.loads(sf.read_text(encoding="utf-8")))
            except Exception:
                pass
    return items
