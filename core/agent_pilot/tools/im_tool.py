"""im.fetch_thread – pull the last N messages of the current chat.

Real Feishu IM history APIs require bot membership + message permissions.
In offline mode we synthesize a deterministic conversation so the
downstream planner / doc generator has something to work with.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

logger = logging.getLogger("pilot.tool.im")


def im_fetch_thread(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}
    chat_id = args.get("chat_id") or ctx.get("chat_id") or ""
    limit = int(args.get("limit") or 20)

    messages = _try_fetch_real(chat_id, limit)
    if not messages:
        messages = _synthetic(limit)

    return {
        "chat_id": chat_id,
        "messages": messages,
        "count": len(messages),
    }


def _try_fetch_real(chat_id: str, limit: int) -> List[Dict[str, Any]]:
    if not chat_id:
        return []
    try:
        from bot.feishu_client import get_client
        import lark_oapi.api.im.v1 as im_api
        client = get_client()
        req = (
            im_api.ListMessageRequest.builder()
            .container_id_type("chat")
            .container_id(chat_id)
            .sort_type("ByCreateTimeDesc")
            .page_size(min(limit, 50))
            .build()
        )
        resp = client.im.v1.message.list(req)
        if not resp.success() or not resp.data or not resp.data.items:
            return []
        out: List[Dict[str, Any]] = []
        for m in resp.data.items:
            text = ""
            try:
                import json as _json
                content = _json.loads(m.body.content) if m.body else {}
                text = content.get("text") or content.get("title") or ""
            except Exception:
                pass
            out.append({
                "sender": getattr(getattr(m, "sender", None), "id", "") or "unknown",
                "ts": int(getattr(m, "create_time", 0) or 0) // 1000,
                "text": text[:200],
                "message_id": getattr(m, "message_id", ""),
            })
        return out
    except Exception as e:
        logger.debug("im.fetch_thread fallback: %s", e)
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
    ][: max(2, min(limit, 6))]
    return [
        {"sender": line.split("：", 1)[0], "ts": base + i * 300,
         "text": line.split("：", 1)[1] if "：" in line else line}
        for i, line in enumerate(convo)
    ]
