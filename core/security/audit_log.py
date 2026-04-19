"""Append-only JSONL audit log.

Every privacy-sensitive action funnels through ``audit(...)``. The log is
rotated daily and never overwritten — required for SOC2-style evidence and
for the rollback feature on the dashboard.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "data" / "audit"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
logger = logging.getLogger("flowguard.security.audit")


@dataclass
class AuditEntry:
    ts: int
    actor: str  # open_id of user OR "system"
    action: str  # tool name
    resource: str  # who/what was acted upon
    outcome: str  # allow | deny | error
    severity: str = "INFO"  # DEBUG | INFO | WARN | HIGH
    meta: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _today_path() -> Path:
    return LOG_DIR / f"{time.strftime('%Y-%m-%d')}.jsonl"


def audit(
    *,
    actor: str,
    action: str,
    resource: str,
    outcome: str,
    severity: str = "INFO",
    meta: Optional[Dict[str, str]] = None,
) -> AuditEntry:
    entry = AuditEntry(
        ts=int(time.time()),
        actor=actor,
        action=action,
        resource=resource,
        outcome=outcome,
        severity=severity,
        meta=meta or {},
    )
    line = json.dumps(entry.to_dict(), ensure_ascii=False)
    with _lock:
        with open(_today_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    if severity in ("WARN", "HIGH"):
        logger.warning("AUDIT %s %s %s actor=%s", severity, action, outcome, actor[-8:])
    return entry


def query_audit(
    *,
    actor: Optional[str] = None,
    actions: Optional[List[str]] = None,
    severities: Optional[List[str]] = None,
    since_ts: int = 0,
    limit: int = 200,
) -> List[AuditEntry]:
    results: List[AuditEntry] = []
    files = sorted(LOG_DIR.glob("*.jsonl"), reverse=True)
    for path in files:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if actor and d.get("actor") != actor:
                    continue
                if actions and d.get("action") not in actions:
                    continue
                if severities and d.get("severity") not in severities:
                    continue
                if d.get("ts", 0) < since_ts:
                    continue
                results.append(AuditEntry(**d))
                if len(results) >= limit:
                    return results
        except Exception as e:
            logger.debug("audit read err %s: %s", path, e)
    return results
