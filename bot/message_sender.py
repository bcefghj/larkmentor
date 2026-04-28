"""Helpers for sending messages and cards via Feishu Bot."""

import json
import logging

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

from bot.feishu_client import get_client

logger = logging.getLogger("flowguard.sender")


def send_text(receive_id: str, text: str, id_type: str = "open_id") -> bool:
    # P1.7 guard: never fire an empty text bubble; Feishu silently accepts
    # {"text": ""} and users see an empty message bubble.
    text = (text or "").strip()
    if not text:
        logger.warning("send_text skipped: empty text to %s", receive_id[-8:] if receive_id else "-")
        return False
    client = get_client()
    body = CreateMessageRequestBody.builder() \
        .receive_id(receive_id) \
        .content(json.dumps({"text": text})) \
        .msg_type("text") \
        .build()
    req = CreateMessageRequest.builder() \
        .receive_id_type(id_type) \
        .request_body(body) \
        .build()
    resp = client.im.v1.message.create(req)
    if not resp.success():
        logger.error("send_text failed: code=%d msg=%s", resp.code, resp.msg)
        return False
    return True


def reply_text(message_id: str, text: str) -> bool:
    # P1.7 guard: empty reply would render a blank bubble.
    text = (text or "").strip()
    if not text:
        logger.warning("reply_text skipped: empty text (message_id=%s)", message_id)
        return False
    client = get_client()
    body = ReplyMessageRequestBody.builder() \
        .content(json.dumps({"text": text})) \
        .msg_type("text") \
        .build()
    req = ReplyMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(body) \
        .build()
    resp = client.im.v1.message.reply(req)
    if not resp.success():
        logger.error("reply_text failed: code=%d msg=%s", resp.code, resp.msg)
        return False
    return True


def send_card(receive_id: str, card: dict, id_type: str = "open_id") -> bool:
    client = get_client()
    body = CreateMessageRequestBody.builder() \
        .receive_id(receive_id) \
        .content(json.dumps(card)) \
        .msg_type("interactive") \
        .build()
    req = CreateMessageRequest.builder() \
        .receive_id_type(id_type) \
        .request_body(body) \
        .build()
    resp = client.im.v1.message.create(req)
    if not resp.success():
        logger.error("send_card failed: code=%d msg=%s", resp.code, resp.msg)
        return False
    return True


def patch_card(message_id: str, card: dict) -> bool:
    """Replace the content of a card via im.v1.message.patch (Card 2.0).

    Feishu's `/im/v1/messages/{id}` PATCH accepts a full card payload; the
    renderer diffs by ``element_id`` so elements not present in ``card`` are
    left untouched. Returns False on any SDK or HTTP failure.
    """
    try:
        from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody
    except ImportError:
        logger.warning("patch_card: lark-oapi PatchMessage unavailable")
        return False
    client = get_client()
    try:
        body = PatchMessageRequestBody.builder().content(json.dumps(card)).build()
        req = PatchMessageRequest.builder().message_id(message_id).request_body(body).build()
        resp = client.im.v1.message.patch(req)
        if not resp.success():
            logger.error("patch_card failed: code=%d msg=%s", resp.code, resp.msg)
            return False
        return True
    except Exception as e:
        logger.exception("patch_card exception: %s", e)
        return False


def reply_card(message_id: str, card: dict) -> bool:
    client = get_client()
    body = ReplyMessageRequestBody.builder() \
        .content(json.dumps(card)) \
        .msg_type("interactive") \
        .build()
    req = ReplyMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(body) \
        .build()
    resp = client.im.v1.message.reply(req)
    if not resp.success():
        logger.error("reply_card failed: code=%d msg=%s", resp.code, resp.msg)
        return False
    return True
