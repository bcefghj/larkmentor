"""Archival: durable storage of compacted summaries inside Feishu.

Three sinks
-----------

* **Local JSONL** – always-on, append-only, used as the source of truth for
  recall queries when Feishu API is unavailable.
* **Bitable** – one row per summary (table ``FlowMemory``).
* **docx**    – one block per summary appended to user's recovery doc.

Both Feishu paths are best-effort: failure is logged but never raised so
classification / replies never block on archival.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_DIR = ROOT / "data" / "archival"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE_FILE = ARCHIVE_DIR / "summaries.jsonl"

logger = logging.getLogger("flowguard.memory.archival")


@dataclass
class ArchivalEntry:
    open_id: str
    ts: int
    span_start: int
    span_end: int
    kind: str  # session | weekly | meeting | manual
    summary_md: str
    meta: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _append_jsonl(entry: ArchivalEntry) -> None:
    line = json.dumps(entry.to_dict(), ensure_ascii=False)
    with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _try_write_bitable(entry: ArchivalEntry) -> Optional[str]:
    """Best-effort Bitable write. Returns record_id or None."""
    try:
        from core.feishu_workspace_init import get_workspace
        from bot.feishu_client import get_client
        from lark_oapi.api.bitable.v1 import (
            CreateAppTableRecordRequest,
            CreateAppTableRecordRequestBody,
            AppTableRecord,
        )

        ws = get_workspace(entry.open_id)
        if not (ws.bitable_app_token and ws.bitable_table_id):
            return None
        client = get_client()
        rec = AppTableRecord.builder().fields({
            "时间": time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.ts)),
            "类型": entry.kind,
            "摘要": entry.summary_md[:500],
        }).build()
        req = (
            CreateAppTableRecordRequest.builder()
            .app_token(ws.bitable_app_token)
            .table_id(ws.bitable_table_id)
            .request_body(
                CreateAppTableRecordRequestBody.builder().fields(rec.fields).build()
            )
            .build()
        )
        resp = client.bitable.v1.app_table_record.create(req)
        if resp.success():
            return resp.data.record.record_id
    except Exception as e:
        logger.debug("bitable archival skipped: %s", e)
    return None


def _try_append_recovery_doc(entry: ArchivalEntry) -> bool:
    try:
        from core.feishu_workspace_init import append_recovery_card
        body = (
            f"### {entry.kind.upper()} · {time.strftime('%Y-%m-%d %H:%M', time.localtime(entry.ts))}\n\n"
            + entry.summary_md
        )
        return append_recovery_card(entry.open_id, body)
    except Exception as e:
        logger.debug("docx archival skipped: %s", e)
        return False


def write_archival_summary(
    open_id: str,
    summary_md: str,
    *,
    kind: str = "session",
    span_start: int = 0,
    span_end: int = 0,
    meta: Optional[Dict[str, str]] = None,
) -> ArchivalEntry:
    """Persist one summary to all three sinks (best-effort)."""
    entry = ArchivalEntry(
        open_id=open_id,
        ts=int(time.time()),
        span_start=span_start or int(time.time()),
        span_end=span_end or int(time.time()),
        kind=kind,
        summary_md=summary_md,
        meta=meta or {},
    )
    try:
        _append_jsonl(entry)
    except Exception as e:
        logger.error("archival jsonl error: %s", e)
    record_id = _try_write_bitable(entry)
    if record_id:
        entry.meta["bitable_record_id"] = record_id
    if _try_append_recovery_doc(entry):
        entry.meta["docx_appended"] = "1"
    return entry


def query_archival(
    open_id: str, *, kinds: Optional[List[str]] = None, since_ts: int = 0, limit: int = 20,
) -> List[ArchivalEntry]:
    """Linear scan of the JSONL store. Good enough at FlowGuard scale (<100k entries)."""
    if not ARCHIVE_FILE.exists():
        return []
    out: List[ArchivalEntry] = []
    with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("open_id") != open_id:
                continue
            if kinds and d.get("kind") not in kinds:
                continue
            if d.get("ts", 0) < since_ts:
                continue
            out.append(ArchivalEntry(**d))
    out.sort(key=lambda x: x.ts, reverse=True)
    return out[:limit]
