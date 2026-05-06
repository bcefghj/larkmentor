"""im.fetch_thread — 从飞书群聊或 EventLog 拉取最近上下文."""

from __future__ import annotations

import logging
import os
from typing import Any

from pilot.context.event_log import EventLog

logger = logging.getLogger("pilot.tool.im_fetch")


def register_to(reg) -> None:
    reg.register(
        "im.fetch_thread",
        description="拉取当前 chat 的最近 N 条消息作为上下文",
        input_schema={
            "type": "object",
            "properties": {
                "chat_id": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
        },
        read_only=True,
        namespace="pilot",
    )(im_fetch_thread)


async def im_fetch_thread(
    *,
    chat_id: str = "",
    limit: int = 50,
    _ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session_id = ""
    if _ctx and _ctx.get("session"):
        try:
            session_id = _ctx["session"].session_id
            chat_id = chat_id or _ctx["session"].chat_id
        except Exception:
            pass

    # 优先从 EventLog 取
    if session_id:
        log = EventLog(session_id)
        events = log.read_kind(["user_message", "assistant_text"])[-limit:]
        msgs = []
        for e in events:
            kind = e.get("kind", "")
            payload = e.get("payload", {}) or {}
            msgs.append({
                "sender": "user" if kind == "user_message" else "assistant",
                "text": payload.get("text", ""),
                "ts": e.get("ts", 0),
            })
        if msgs:
            return {"chat_id": chat_id, "messages": msgs, "source": "event_log"}

    # 尝试飞书 API
    if chat_id and os.getenv("FEISHU_APP_ID"):
        try:
            from pilot.surface.feishu.client import get_feishu_client

            client = get_feishu_client()
            msgs = await client.get_chat_messages(chat_id=chat_id, limit=limit)
            return {"chat_id": chat_id, "messages": msgs, "source": "feishu"}
        except Exception as e:
            logger.warning("im.fetch_thread feishu failed: %s", e)

    return {"chat_id": chat_id, "messages": [], "source": "empty"}
