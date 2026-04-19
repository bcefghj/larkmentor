"""Reply-in-thread helper so auto-replies don't spam group chats."""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional

logger = logging.getLogger("flowguard.feishu.thread")


def reply_in_thread(message_id: str, text: str, *, msg_type: str = "text") -> Dict:
    """Reply to ``message_id`` inside its thread instead of posting to the chat root."""
    try:
        from bot.feishu_client import get_client
        from lark_oapi.api.im.v1 import (  # type: ignore
            ReplyMessageRequest, ReplyMessageRequestBody,
        )
        client = get_client()
        if msg_type == "text":
            content = json.dumps({"text": text}, ensure_ascii=False)
        else:
            content = text  # caller supplies pre-serialised JSON
        req = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .content(content)
                .msg_type(msg_type)
                .reply_in_thread(True)
                .build()
            )
            .build()
        )
        resp = client.im.v1.message.reply(req)
        return {
            "ok": resp.success(),
            "message_id": getattr(getattr(resp, "data", None), "message_id", None),
            "code": getattr(resp, "code", None),
        }
    except Exception as e:
        logger.debug("reply_in_thread err: %s", e)
        return {"ok": False, "error": str(e)}
