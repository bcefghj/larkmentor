"""IM Tools · 把原 Shield v3 + Recovery Card + Feishu message send 塌缩为 @tool。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .registry import tool

logger = logging.getLogger("agent.tools.im")


@tool(
    name="im.triage",
    description="6 维分类（身份/关系/内容/任务/时间/频道），返回 P0-P3 分级 + 是否立即推送",
    permission="readonly",
    team="any",
)
def triage_message(
    sender_name: str = "",
    sender_id: str = "",
    content: str = "",
    chat_name: str = "",
    chat_type: str = "group",
    user_open_id: str = "",
) -> Dict[str, Any]:
    """原 core.smart_shield_v3.process_message_v3 的薄 wrapper."""
    try:
        from memory.user_state import get_user
        from core.smart_shield_v3 import process_message_v3
        user = get_user(user_open_id) if user_open_id else None
        if user is None:
            return {
                "level": "P2", "score": 0.3,
                "recommended_action": "defer",
                "note": "user not found, default P2",
            }
        result = process_message_v3(
            user=user,
            sender_name=sender_name, sender_id=sender_id,
            message_id="", content=content, chat_name=chat_name,
            chat_type=chat_type,
        )
        return {"level": result.get("level", "P2"), **result}
    except Exception as e:
        logger.warning("im.triage fallback: %s", e)
        return {"level": "P2", "score": 0.3, "error": str(e)}


@tool(
    name="im.send_text",
    description="发送文本消息到 Feishu chat_id / open_id",
    permission="write",
    team="any",
)
def send_text(chat_id: str = "", open_id: str = "", text: str = "") -> Dict[str, Any]:
    try:
        from bot.message_sender import send_text as _send_text
        ok = _send_text(chat_id or open_id, text)
        return {"ok": ok, "target": chat_id or open_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="im.send_card",
    description="发送 Card 2.0 交互卡片",
    permission="write",
    team="any",
)
def send_card(chat_id: str = "", open_id: str = "", card: Optional[Dict] = None) -> Dict[str, Any]:
    try:
        from bot.message_sender import send_card as _send_card
        msg_id = _send_card(chat_id or open_id, card or {})
        return {"ok": bool(msg_id), "message_id": msg_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="im.recovery_card",
    description="专注结束后推 Recovery Card（展示被挡消息+起草回复）",
    permission="write",
    team="any",
)
def recovery_card(user_open_id: str = "", focus_start_ts: int = 0) -> Dict[str, Any]:
    try:
        from core.recovery_card import send_recovery_card
        ok = send_recovery_card(user_open_id=user_open_id, focus_start_ts=focus_start_ts)
        return {"ok": bool(ok)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="im.get_history",
    description="获取某个会话最近 N 条消息",
    permission="readonly",
    team="any",
)
def get_history(chat_id: str = "", limit: int = 20) -> Dict[str, Any]:
    try:
        from bot.feishu_client import get_client
        client = get_client()
        from lark_oapi.api.im.v1 import ListMessageRequest
        req = ListMessageRequest.builder().container_id_type("chat").container_id(chat_id).page_size(limit).build()
        resp = client.im.v1.message.list(req)
        items = []
        if resp.success() and resp.data:
            for item in (resp.data.items or []):
                items.append({
                    "message_id": getattr(item, "message_id", ""),
                    "sender_id": getattr(getattr(item, "sender", None), "id", ""),
                    "content": str(getattr(item, "body", ""))[:500],
                })
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
