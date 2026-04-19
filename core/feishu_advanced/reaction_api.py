"""Emoji-reaction wrappers (im:message.reaction)."""

from __future__ import annotations

import logging
from typing import Dict, List

logger = logging.getLogger("flowguard.feishu.reaction")


def add_reaction(message_id: str, emoji_type: str = "EYES") -> Dict:
    """Add an emoji reaction (defaults to 👀 for low-friction P3 ack)."""
    try:
        from bot.feishu_client import get_client
        from lark_oapi.api.im.v1 import (  # type: ignore
            CreateMessageReactionRequest, CreateMessageReactionRequestBody, Emoji,
        )
        client = get_client()
        req = (
            CreateMessageReactionRequest.builder()
            .message_id(message_id)
            .request_body(
                CreateMessageReactionRequestBody.builder()
                .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
                .build()
            )
            .build()
        )
        resp = client.im.v1.message_reaction.create(req)
        return {"ok": resp.success(), "code": getattr(resp, "code", None)}
    except Exception as e:
        logger.debug("reaction add err: %s", e)
        return {"ok": False, "error": str(e)}


def list_reactions(message_id: str) -> List[Dict]:
    try:
        from bot.feishu_client import get_client
        from lark_oapi.api.im.v1 import ListMessageReactionRequest  # type: ignore
        client = get_client()
        req = ListMessageReactionRequest.builder().message_id(message_id).build()
        resp = client.im.v1.message_reaction.list(req)
        if not resp.success() or not resp.data or not getattr(resp.data, "items", None):
            return []
        return [
            {
                "user_id": getattr(getattr(it, "operator", None), "operator_id", ""),
                "emoji": getattr(getattr(it, "reaction_type", None), "emoji_type", ""),
            }
            for it in resp.data.items
        ]
    except Exception as e:
        logger.debug("reaction list err: %s", e)
        return []
