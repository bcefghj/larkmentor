"""Feishu Open API helper functions for calendar, tasks, contacts, and bitable."""

import json
import logging
import time

import lark_oapi as lark
from lark_oapi.api.contact.v3 import GetUserRequest
from lark_oapi.api.bitable.v1 import (
    CreateAppTableRecordRequest,
    CreateAppTableRecordRequestBody,
    AppTableRecord,
)

from bot.feishu_client import get_client
from config import Config
from memory.user_state import get_cached_name, set_cached_name

logger = logging.getLogger("flowguard.api")


# ── Contact: resolve user name ──

def resolve_user_name(open_id: str) -> str:
    """Get user's display name from Feishu contacts API, with caching."""
    cached = get_cached_name(open_id)
    if cached:
        return cached
    try:
        client = get_client()
        req = GetUserRequest.builder().user_id(open_id).user_id_type("open_id").build()
        resp = client.contact.v3.user.get(req)
        if resp.success() and resp.data and resp.data.user:
            name = resp.data.user.name or open_id
            set_cached_name(open_id, name)
            return name
        else:
            logger.debug("resolve_user_name failed: code=%s msg=%s", resp.code, resp.msg)
    except Exception as e:
        logger.debug("resolve_user_name error: %s", e)
    return open_id


# ── Calendar ──

def get_current_calendar_events() -> list:
    """Fetch primary calendar events happening right now using tenant token.

    Returns list of event summary strings that match focus keywords.
    """
    try:
        client = get_client()
        now_sec = int(time.time())
        # Query events from now to now (current moment overlap)
        import lark_oapi.api.calendar.v4 as cal_api

        req = (
            cal_api.ListCalendarEventRequest.builder()
            .calendar_id("primary")
            .start_time(str(now_sec))
            .end_time(str(now_sec + 300))
            .build()
        )
        resp = client.calendar.v4.calendar_event.list(req)
        if resp.success() and resp.data and resp.data.items:
            results = []
            for ev in resp.data.items:
                summary = ev.summary or ""
                results.append(summary)
            return results
        return []
    except Exception as e:
        logger.debug("Calendar API error (non-critical): %s", e)
        return []


# ── Tasks ──

def get_user_tasks() -> list:
    """Fetch current user's incomplete tasks (simplified)."""
    return []


# ── Bitable ──

def log_to_bitable(fields: dict) -> bool:
    if not Config.BITABLE_APP_TOKEN or not Config.BITABLE_TABLE_ID:
        return False
    client = get_client()
    req = (
        CreateAppTableRecordRequest.builder()
        .app_token(Config.BITABLE_APP_TOKEN)
        .table_id(Config.BITABLE_TABLE_ID)
        .request_body(AppTableRecord.builder().fields(fields).build())
        .build()
    )
    resp = client.bitable.v1.app_table_record.create(req)
    if not resp.success():
        logger.error("bitable write failed: code=%d msg=%s", resp.code, resp.msg)
        return False
    return True


def log_interruption_to_bitable(
    timestamp: str, sender: str, level: str, action: str, chat_name: str,
) -> bool:
    return log_to_bitable({
        "时间": timestamp, "消息来源": sender, "优先级": level,
        "处理方式": action, "频道": chat_name,
    })
