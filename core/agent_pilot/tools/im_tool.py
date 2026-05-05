"""im.fetch_thread – pull the last N messages of the current chat.

Real Feishu IM history APIs require bot membership + message permissions.
In offline mode we synthesize a deterministic conversation so the
downstream planner / doc generator has something to work with.

Supports:
- Paginated fetching via im/v1/messages API
- Message type filtering (text, post, interactive)
- PII scrubbing before downstream consumption
- lark-cli fallback when SDK is unavailable
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pilot.tool.im")


def im_fetch_thread(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}
    chat_id = args.get("chat_id") or ctx.get("chat_id") or ""
    try:
        limit = int(args.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20

    # Also pull from ContextPack source_messages if available
    cp = ctx.get("context_pack")
    cp_messages: List[Dict[str, Any]] = []
    if cp and hasattr(cp, "source_messages") and cp.source_messages:
        cp_messages = [
            {"sender": m.sender_open_id, "ts": m.ts, "text": m.text, "message_id": getattr(m, "msg_id", "")}
            for m in cp.source_messages
        ]

    messages = _try_fetch_real(chat_id, limit)
    if not messages:
        messages = _try_fetch_via_cli(chat_id, limit)
    synthetic = False
    if not messages:
        if cp_messages:
            messages = cp_messages
        else:
            messages = _synthetic(limit)
            synthetic = True

    scrubbed, report = _scrub_messages(messages)

    return {
        "chat_id": chat_id,
        "messages": scrubbed,
        "count": len(scrubbed),
        "synthetic": synthetic,
        "pii_redactions": report,
    }


def im_send_message(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Send a message to a chat (used by orchestrator for progress updates)."""
    args = ctx.get("resolved_args") or {}
    chat_id = args.get("chat_id") or ctx.get("chat_id") or ""
    text = args.get("text") or ""
    if not chat_id or not text:
        return {"ok": False, "error": "chat_id and text required"}

    try:
        import lark_oapi.api.im.v1 as im_api

        from bot.feishu_client import get_client

        client = get_client()
        content = json.dumps({"text": text})
        req = (
            im_api.CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                im_api.CreateMessageRequestBody.builder().receive_id(chat_id).msg_type("text").content(content).build()
            )
            .build()
        )
        resp = client.im.v1.message.create(req)
        if resp.success():
            return {"ok": True, "message_id": resp.data.message_id if resp.data else ""}
        return {"ok": False, "error": f"code={getattr(resp, 'code', '?')}"}
    except Exception as e:
        logger.debug("im.send fallback: %s", e)
        return {"ok": False, "error": str(e)}


def _scrub_messages(messages: List[Dict[str, Any]]):
    try:
        from core.security.pii_scrubber import scrub_pii  # type: ignore
    except Exception:
        return messages, {}
    counts: Dict[str, int] = {}
    out = []
    for m in messages:
        r = scrub_pii(m.get("text") or "")
        new_m = dict(m)
        new_m["text"] = r.redacted_text
        for k, v in (r.counts or {}).items():
            counts[k] = counts.get(k, 0) + v
        out.append(new_m)
    return out, counts


def _try_fetch_real(chat_id: str, limit: int) -> List[Dict[str, Any]]:
    if not chat_id:
        return []
    try:
        import lark_oapi.api.im.v1 as im_api

        from bot.feishu_client import get_client

        client = get_client()

        all_messages: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        remaining = limit

        while remaining > 0:
            page_size = min(remaining, 50)
            builder = (
                im_api.ListMessageRequest.builder()
                .container_id_type("chat")
                .container_id(chat_id)
                .sort_type("ByCreateTimeDesc")
                .page_size(page_size)
            )
            if page_token:
                builder = builder.page_token(page_token)
            req = builder.build()

            resp = client.im.v1.message.list(req)
            if not resp.success() or not resp.data or not resp.data.items:
                break

            for m in resp.data.items:
                msg_type = getattr(m, "msg_type", "text")
                if msg_type not in ("text", "post", "interactive"):
                    continue
                text = _extract_text(m)
                if not text:
                    continue
                all_messages.append(
                    {
                        "sender": getattr(getattr(m, "sender", None), "id", "") or "unknown",
                        "ts": int(getattr(m, "create_time", 0) or 0) // 1000,
                        "text": text[:500],
                        "message_id": getattr(m, "message_id", ""),
                        "msg_type": msg_type,
                    }
                )

            remaining -= len(resp.data.items)
            page_token = getattr(resp.data, "page_token", None)
            if not getattr(resp.data, "has_more", False):
                break

        return all_messages
    except Exception as e:
        logger.debug("im.fetch_thread sdk fallback: %s", e)
        return []


def _extract_text(m) -> str:
    """Extract text content from various message types."""
    try:
        body = m.body if hasattr(m, "body") else None
        if not body or not body.content:
            return ""
        content = json.loads(body.content)
        msg_type = getattr(m, "msg_type", "text")
        if msg_type == "text":
            return content.get("text", "")
        if msg_type == "post":
            title = content.get("title", "")
            paragraphs = []
            for lang_content in content.get("content", []):
                if isinstance(lang_content, list):
                    for elem in lang_content:
                        if isinstance(elem, dict) and elem.get("tag") == "text":
                            paragraphs.append(elem.get("text", ""))
            return f"{title}\n{''.join(paragraphs)}" if paragraphs else title
        if msg_type == "interactive":
            return content.get("header", {}).get("title", {}).get("content", "")
        return ""
    except Exception:
        return ""


def _try_fetch_via_cli(chat_id: str, limit: int) -> List[Dict[str, Any]]:
    """Fallback: try lark-cli messenger read."""
    if not chat_id:
        return []
    try:
        import shutil
        import subprocess

        cli = shutil.which("lark-cli") or shutil.which("lark")
        if not cli:
            return []
        result = subprocess.run(
            [cli, "messenger", "read", "--chat-id", chat_id, "--limit", str(min(limit, 50)), "--output", "json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        messages = data if isinstance(data, list) else data.get("messages", [])
        return [
            {
                "sender": m.get("sender", "unknown"),
                "ts": m.get("ts", 0),
                "text": m.get("text", "")[:500],
                "message_id": m.get("message_id", ""),
            }
            for m in messages[:limit]
        ]
    except Exception as e:
        logger.debug("im.fetch_thread cli fallback: %s", e)
        return []


def _synthetic(limit: int) -> List[Dict[str, Any]]:
    base = int(time.time()) - 3600
    convo = [
        "戴尚好：本周我们讨论一下 Agent-Pilot 的架构吧",
        "李洁盈：我觉得核心是 IM → Doc → PPT 这条主线",
        "戴尚好：嗯，Planner 应该把自然语言拆成 DAG",
        "李洁盈：多端同步用 Yjs，离线也能编辑",
        "戴尚好：Docx 用飞书 API，Canvas 双写，PPT 用 Slidev",
        "李洁盈：我来出 demo 脚本，你把 Planner 跑通",
        "戴尚好：安全方面我加了 8 层防护栈，OWASP LLM Top 10 全覆盖",
        "李洁盈：Memory 体系也要跑通，6 层继承",
        "戴尚好：好的，我来把 orchestrator 到 tools 的链路打通",
        "李洁盈：三线产品的合体点也很重要，Shield+Mentor+Pilot 要真正联动",
    ][: max(2, min(limit, 10))]
    return [
        {
            "sender": line.split("：", 1)[0],
            "ts": base + i * 300,
            "text": line.split("：", 1)[1] if "：" in line else line,
            "message_id": f"syn_msg_{i}",
        }
        for i, line in enumerate(convo)
    ]
