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
