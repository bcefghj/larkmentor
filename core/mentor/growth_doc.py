"""Growth Journal · auto-maintained Feishu Docx for each user.

Behaviour:
- First call to ``ensure_growth_doc(open_id)`` creates the doc, persists the
  token onto the user's state, and stamps a header.
- Every Mentor action (writing review / task clarification / proactive
  suggestion picked) appends a structured entry via ``append_entry``.
- A weekly cron (Sunday 21:00, scheduled in main.py) calls ``write_summary``
  which asks the LLM to summarise the past week's entries in <=200 chars
  and appends a "本周成长摘要" block.

All Feishu API calls are best-effort -- failures are logged and swallowed
so they never block the bot's main loop.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("flowguard.mentor.growth")


# ── persistence (entries log lives next to mentor KB) ─────────────────────────

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
_LOG_PATH = os.path.join(_DATA_DIR, "growth_entries.jsonl")


@dataclass
class GrowthEntry:
    open_id: str
    ts: int
    kind: str              # "writing" | "task" | "proactive_picked" | "weekly"
    original: str
    improved: str
    citations: List[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "open_id": self.open_id, "ts": self.ts, "kind": self.kind,
                "original": self.original, "improved": self.improved,
                "citations": self.citations, "extra": self.extra,
            },
            ensure_ascii=False,
        )


def _append_log(entry: GrowthEntry) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(entry.to_json() + "\n")
    except Exception as e:  # noqa: BLE001
        logger.warning("growth_log_fail err=%s", e)


def load_entries(open_id: str, *, since_ts: int = 0) -> List[GrowthEntry]:
    if not os.path.exists(_LOG_PATH):
        return []
    out: List[GrowthEntry] = []
    try:
        with open(_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("open_id") != open_id:
                    continue
                if since_ts and int(d.get("ts", 0)) < since_ts:
                    continue
                out.append(
                    GrowthEntry(
                        open_id=d.get("open_id", ""),
                        ts=int(d.get("ts", 0)),
                        kind=d.get("kind", ""),
                        original=d.get("original", ""),
                        improved=d.get("improved", ""),
                        citations=d.get("citations", []) or [],
                        extra=d.get("extra", {}) or {},
                    )
                )
    except Exception as e:  # noqa: BLE001
        logger.warning("growth_load_fail err=%s", e)
    return out


# ── Feishu Docx helpers ──────────────────────────────────────────────────────

def _create_docx(title: str, body_md: str) -> Optional[str]:
    """Return the new docx token or None on failure. Mirrors v3 _create_doc."""
    try:
        from bot.feishu_client import get_client
        import lark_oapi.api.docx.v1 as docx_api

        client = get_client()
        req = (
            docx_api.CreateDocumentRequest.builder()
            .request_body(
                docx_api.CreateDocumentRequestBody.builder().title(title).build()
            )
            .build()
        )
        resp = client.docx.v1.document.create(req)
        if not resp.success():
            logger.warning("growth_create_fail code=%s msg=%s", resp.code, resp.msg)
            return None
        token = resp.data.document.document_id
        try:
            _append_block(token, body_md)
        except Exception as e:  # noqa: BLE001
            logger.debug("growth_seed_fail err=%s", e)
        return token
    except Exception as e:  # noqa: BLE001
        logger.warning("growth_docx_unavailable err=%s", e)
        return None


def _append_block(doc_token: str, content: str) -> bool:
    try:
        from bot.feishu_client import get_client
        from lark_oapi.api.docx.v1 import (
            CreateDocumentBlockChildrenRequest,
            CreateDocumentBlockChildrenRequestBody,
            Block, Text, TextElement, TextRun,
        )

        client = get_client()
        text_run = TextRun.builder().content(content).build()
        text_el = TextElement.builder().text_run(text_run).build()
        text = Text.builder().elements([text_el]).build()
        block = Block.builder().block_type(2).text(text).build()
        req = (
            CreateDocumentBlockChildrenRequest.builder()
            .document_id(doc_token)
            .block_id(doc_token)
            .request_body(
                CreateDocumentBlockChildrenRequestBody.builder()
                .children([block]).build()
            )
            .build()
        )
        resp = client.docx.v1.document_block_children.create(req)
        return bool(resp.success())
    except Exception as e:  # noqa: BLE001
        logger.debug("growth_append_fail err=%s", e)
        return False


# ── public API ───────────────────────────────────────────────────────────────

def ensure_growth_doc(open_id: str) -> str:
    """Return the docx token for the user's growth journal, creating if needed.

    Returns "" if Feishu API is unavailable (caller handles graceful degrade).
    """
    try:
        from memory.user_state import get_user

        user = get_user(open_id)
    except Exception:
        user = None

    if user and getattr(user, "growth_doc_token", ""):
        return user.growth_doc_token

    seed = (
        "# 我的新手成长记录\n\n"
        "本文档由 LarkMentor 自动维护。每次 Mentor 出手协助你（写消息、拆任务、写周报、起草回复），"
        "都会在这里追加一条记录。每周日 21:00 会自动生成一段成长摘要。\n\n"
        "---\n"
    )
    token = _create_docx(f"LarkMentor · 我的新手成长记录", seed)
    if token and user:
        user.growth_doc_token = token
        try:
            from memory.user_state import _save_all  # type: ignore

            _save_all()
        except Exception:
            pass
    return token or ""


def append_entry(
    open_id: str,
    *,
    kind: str,
    original: str,
    improved: str,
    citations: Optional[List[str]] = None,
    extra: Optional[dict] = None,
) -> None:
    """Append a Mentor action to both the local jsonl log and the Feishu Docx."""
    entry = GrowthEntry(
        open_id=open_id, ts=int(time.time()), kind=kind,
        original=original or "", improved=improved or "",
        citations=list(citations or []), extra=dict(extra or {}),
    )
    _append_log(entry)

    token = ensure_growth_doc(open_id)
    if not token:
        return

    ts_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.ts))
    cite = " ".join(entry.citations) if entry.citations else ""
    body = (
        f"\n## [{kind}] {ts_str}\n"
        f"- 原文：{entry.original[:300]}\n"
        f"- 改写/建议：{entry.improved[:300]}\n"
        + (f"- 引用：{cite}\n" if cite else "")
    )
    _append_block(token, body)


def write_weekly_summary(open_id: str) -> Optional[str]:
    """Generate a <=200-char weekly summary and append to the doc.

    Called by the scheduler every Sunday 21:00.
    Returns the summary text or None if no entries this week.
    """
    week_start = int(time.time()) - 7 * 86400
    entries = load_entries(open_id, since_ts=week_start)
    if not entries:
        return None

    lines = [
        f"- [{e.kind}] {e.original[:60]} -> {e.improved[:60]}"
        for e in entries[-30:]
    ]
    payload = "\n".join(lines)

    summary = ""
    try:
        from llm.llm_client import chat
        from llm.prompts import MENTOR_GROWTH_SUMMARY_PROMPT

        summary = chat(
            MENTOR_GROWTH_SUMMARY_PROMPT.format(entries=payload),
            temperature=0.4,
        ) or ""
    except Exception as e:  # noqa: BLE001
        logger.warning("growth_summary_llm_fail err=%s", e)

    if not summary:
        summary = (
            f"本周共有 {len(entries)} 次 Mentor 出手记录，覆盖 "
            f"{len(set(e.kind for e in entries))} 种场景。建议下周回看本档案，注意"
            f"重复出现的沟通模式。"
        )

    token = ensure_growth_doc(open_id)
    if token:
        ts_str = time.strftime("%Y-%m-%d", time.localtime())
        _append_block(token, f"\n## 本周成长摘要 · {ts_str}\n{summary}\n")

    return summary
