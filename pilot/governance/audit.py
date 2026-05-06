"""审计日志 — append-only 落盘所有 tool_call / decision / approval.

文件结构:
  data/audit/<yyyy-mm-dd>/audit.jsonl

每条记录:
  {"ts": ..., "kind": "tool_call|permission_check|approval|owner_change",
   "session_id": "...", "task_id": "...", "actor": "...", "tool": "...",
   "verdict": "...", "reason": "...", "input": {...}, "output_summary": "..."}
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("pilot.governance.audit")

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data"))).resolve()
AUDIT_DIR = DATA_DIR / "audit"


class AuditLog:
    def __init__(self) -> None:
        self._mutex = threading.Lock()

    def _today_path(self) -> Path:
        d = AUDIT_DIR / time.strftime("%Y-%m-%d")
        d.mkdir(parents=True, exist_ok=True)
        return d / "audit.jsonl"

    def write(self, *, kind: str, **fields: Any) -> dict[str, Any]:
        record = {
            "ts": time.time(),
            "kind": kind,
            **fields,
        }
        try:
            with self._mutex:
                with self._today_path().open("a", encoding="utf-8") as fp:
                    fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("audit write failed: %s", e)
        return record

    def read_recent(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """读今天 + 昨天的 audit log（粗略）."""
        out = []
        for delta in (0, 1):
            ts_str = time.strftime("%Y-%m-%d", time.localtime(time.time() - delta * 86400))
            f = AUDIT_DIR / ts_str / "audit.jsonl"
            if not f.exists():
                continue
            try:
                for line in f.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
            except Exception:
                pass
        out.sort(key=lambda r: r.get("ts", 0), reverse=True)
        return out[:limit]


_default: AuditLog | None = None


def default_audit() -> AuditLog:
    global _default
    if _default is None:
        _default = AuditLog()
    return _default
