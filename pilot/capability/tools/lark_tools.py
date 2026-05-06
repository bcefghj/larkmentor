"""V1.5 — 飞书 OpenAPI 真集成工具子集（lark.* 命名空间）.

设计取舍:
  - 不引入 larksuite/cli 24 SKILL submodule（那只是 markdown 文档，并非可执行代码）。
  - 改用我们自有的 pilot.surface.feishu.client.FeishuClient（纯 httpx 封装），
    实现 3 个真用得上的 OpenAPI 调用：
      - lark.im.fetch_thread   群聊消息抓取
      - lark.doc.search        云文档检索
      - lark.bitable.search    多维表格记录检索
  - 命名空间 "lark"，registry 注册时与 pilot 内置工具区分。

未注入飞书凭据（FEISHU_APP_ID/SECRET）时，工具返回 ok=False + reason，不抛异常。
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("pilot.tool.lark")


def register_to(reg) -> None:
    reg.register(
        "lark.im.fetch_thread",
        description="飞书群聊消息抓取（最近 N 条）。需配置 FEISHU_APP_ID + bot 在该群里",
        input_schema={
            "type": "object",
            "properties": {
                "chat_id": {"type": "string", "description": "目标 chat_id（留空则用 _ctx.chat_id）"},
                "limit": {"type": "integer", "description": "返回最近 N 条，默认 50", "default": 50},
            },
            "required": [],
        },
        read_only=True,
        namespace="lark",
    )(lark_im_fetch_thread)

    reg.register(
        "lark.doc.search",
        description="飞书云文档检索（Drive search API）",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "count": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        read_only=True,
        namespace="lark",
    )(lark_doc_search)

    reg.register(
        "lark.bitable.search",
        description="多维表格记录检索（按 query 模糊匹配，需配 FEISHU_BITABLE_APP_TOKEN + table_id）",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "app_token": {"type": "string"},
                "table_id": {"type": "string"},
                "page_size": {"type": "integer", "default": 20},
            },
            "required": ["table_id"],
        },
        read_only=True,
        namespace="lark",
    )(lark_bitable_search)


def _has_feishu_credentials() -> bool:
    app_id = os.getenv("FEISHU_APP_ID", "")
    return bool(app_id) and app_id != "cli_your_app_id_here" and bool(os.getenv("FEISHU_APP_SECRET"))


async def lark_im_fetch_thread(
    *,
    chat_id: str = "",
    limit: int = 50,
    _ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _has_feishu_credentials():
        return {"ok": False, "reason": "no_feishu_credentials", "messages": []}

    if not chat_id and _ctx:
        chat_id = (_ctx.get("chat_id") or "") or (_ctx.get("session", {}) and getattr(_ctx["session"], "chat_id", "")) or ""

    if not chat_id:
        return {"ok": False, "reason": "missing_chat_id", "messages": []}

    try:
        from pilot.surface.feishu.client import get_feishu_client

        msgs = await get_feishu_client().get_chat_messages(chat_id=chat_id, limit=int(limit))
    except Exception as e:
        logger.warning("lark.im.fetch_thread failed: %s", e)
        return {"ok": False, "reason": "feishu_call_failed", "error": str(e)[:200], "messages": []}

    return {
        "ok": True,
        "chat_id": chat_id,
        "count": len(msgs),
        "messages": msgs,
    }


async def lark_doc_search(
    *,
    query: str,
    count: int = 10,
    _ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _has_feishu_credentials():
        return {"ok": False, "reason": "no_feishu_credentials", "results": []}
    if not query:
        return {"ok": False, "reason": "empty_query", "results": []}

    try:
        from pilot.surface.feishu.client import get_feishu_client

        results = await get_feishu_client().drive_search(query=query, count=int(count))
    except Exception as e:
        logger.warning("lark.doc.search failed: %s", e)
        return {"ok": False, "reason": "feishu_call_failed", "error": str(e)[:200], "results": []}

    return {"ok": True, "query": query, "count": len(results), "results": results}


async def lark_bitable_search(
    *,
    table_id: str = "",
    query: str = "",
    app_token: str = "",
    page_size: int = 20,
    _ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _has_feishu_credentials():
        return {"ok": False, "reason": "no_feishu_credentials", "records": []}
    if not table_id:
        return {"ok": False, "reason": "missing_table_id", "records": []}

    try:
        from pilot.surface.feishu.client import get_feishu_client

        records = await get_feishu_client().bitable_search(
            app_token=app_token, table_id=table_id, query=query, page_size=int(page_size),
        )
    except Exception as e:
        logger.warning("lark.bitable.search failed: %s", e)
        return {"ok": False, "reason": "feishu_call_failed", "error": str(e)[:200], "records": []}

    return {
        "ok": True,
        "app_token": app_token or os.getenv("FEISHU_BITABLE_APP_TOKEN", ""),
        "table_id": table_id,
        "query": query,
        "count": len(records),
        "records": records,
    }
