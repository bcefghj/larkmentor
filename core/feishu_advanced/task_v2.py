"""Create a Feishu Task v2 from a P0 message that contains task-like keywords."""

from __future__ import annotations

import logging
from typing import Dict, List

logger = logging.getLogger("flowguard.feishu.task")


TASK_KEYWORDS = ("待办", "todo", "TODO", "请处理", "需要", "请你",
                 "deadline", "DDL", "下班前", "今天前", "by EOD")


def looks_like_task(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(kw.lower() in t for kw in TASK_KEYWORDS)


def create_task_from_message(
    *, open_id: str, summary: str, message_id: str = "",
    due_ts: int = 0,
) -> Dict:
    """Create a Tasks v2 task assigned to ``open_id``."""
    try:
        from bot.feishu_client import get_client
        from lark_oapi.api.task.v2 import (  # type: ignore
            CreateTaskRequest, InputTask, Member,
        )
        client = get_client()
        members: List = [
            Member.builder().id(open_id).id_type("open_id").role("assignee").build()
        ]
        body = (
            InputTask.builder()
            .summary(summary[:120])
            .description(f"LarkMentor 自动创建（来源 message_id={message_id}）")
            .members(members)
            .build()
        )
        if due_ts:
            try:
                from lark_oapi.api.task.v2 import Due  # type: ignore
                body.due = Due.builder().timestamp(str(due_ts * 1000)).build()
            except Exception:
                pass
        req = (
            CreateTaskRequest.builder()
            .user_id_type("open_id")
            .request_body(body)
            .build()
        )
        resp = client.task.v2.task.create(req)
        if not resp.success():
            return {"ok": False, "code": resp.code, "msg": resp.msg}
        return {"ok": True, "task_guid": getattr(resp.data.task, "guid", "")}
    except Exception as e:
        logger.debug("task create err: %s", e)
        return {"ok": False, "error": str(e)}
