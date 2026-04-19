"""Auto-create busy calendar entries when the user enters focus mode."""

from __future__ import annotations

import logging
import time
from typing import Dict

logger = logging.getLogger("flowguard.feishu.calendar")


def create_busy_event(
    open_id: str, *, summary: str = "FlowGuard 专注时间", duration_min: int = 30,
) -> Dict:
    """Create a single-tenant busy event in the user's primary calendar."""
    try:
        from bot.feishu_client import get_client
        from lark_oapi.api.calendar.v4 import (  # type: ignore
            CreateCalendarEventRequest, CalendarEvent, TimeInfo,
        )
        client = get_client()
        # Locate the primary calendar for this user.
        primary_id = _get_primary_calendar_id(open_id)
        if not primary_id:
            return {"ok": False, "reason": "no_primary_calendar"}

        start_ts = int(time.time())
        end_ts = start_ts + duration_min * 60
        event = (
            CalendarEvent.builder()
            .summary(summary)
            .description("由 FlowGuard 自动创建。请勿打扰，专注会话结束后自动取消。")
            .start_time(TimeInfo.builder().timestamp(str(start_ts)).build())
            .end_time(TimeInfo.builder().timestamp(str(end_ts)).build())
            .visibility("private")
            .build()
        )
        req = (
            CreateCalendarEventRequest.builder()
            .calendar_id(primary_id).user_id_type("open_id")
            .event(event).build()
        )
        resp = client.calendar.v4.calendar_event.create(req)
        if not resp.success():
            return {"ok": False, "code": resp.code, "msg": resp.msg}
        return {
            "ok": True,
            "event_id": getattr(getattr(resp, "data", None), "event", None) and resp.data.event.event_id,
            "calendar_id": primary_id,
        }
    except Exception as e:
        logger.debug("calendar busy err: %s", e)
        return {"ok": False, "error": str(e)}


def _get_primary_calendar_id(open_id: str) -> str:
    try:
        from bot.feishu_client import get_client
        from lark_oapi.api.calendar.v4 import ListCalendarRequest  # type: ignore
        client = get_client()
        req = ListCalendarRequest.builder().user_id_type("open_id").build()
        resp = client.calendar.v4.calendar.list(req)
        if not resp.success() or not resp.data or not getattr(resp.data, "calendar_list", None):
            return ""
        for cal in resp.data.calendar_list:
            if getattr(cal, "type", "") == "primary":
                return cal.calendar_id
        # Fallback: first calendar.
        return resp.data.calendar_list[0].calendar_id
    except Exception:
        return ""
