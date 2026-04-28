"""Bitable ↔ Agent-Pilot integration.

Flow
----
* 多维表格某行新增/更新 → 飞书 AI Agent 节点 webhook 打到 ``/api/pilot/bitable``
* 我们的 FastAPI 路由把行字段转成一个自然语言 intent，交给 PilotService.launch
* 执行结束后把 share_url + verdict 回写到 Bitable ``AI 结果`` 字段

这个模块既是 "触发入口" 又是 "回写出口"。两种入口是同一套：
    POST /api/pilot/bitable
         { "app_token": "...", "table_id": "...", "record_id": "...",
           "intent_template": "{需求} 生成文档+PPT",
           "fields": {...} }
回写：``PATCH /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}``
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger("flowguard.feishu.bitable_agent")


def build_intent_from_fields(fields: Dict[str, Any], template: str = "") -> str:
    """Render intent string from Bitable record fields using a template.

    Template supports ``{field_name}`` placeholders. Missing fields render
    as empty string (not the literal placeholder).
    """
    template = template or "{需求}"
    try:
        return template.format_map(_SafeDict(fields))
    except Exception:
        return template


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


def writeback_ai_result(
    *,
    app_token: str,
    table_id: str,
    record_id: str,
    ai_field_name: str,
    verdict: str,
    share_url: str,
    extra: Optional[Dict[str, Any]] = None,
) -> bool:
    """PATCH the Bitable record with a formatted AI result cell."""
    try:
        from bot.feishu_client import get_tenant_access_token  # type: ignore
        tat = get_tenant_access_token()
        if not tat:
            return False
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}"
            f"/tables/{table_id}/records/{record_id}"
        )
        cell_value = {
            "text": f"{verdict}\n{share_url}",
            "status": verdict,
        }
        if extra:
            cell_value.update(extra)
        payload = {"fields": {ai_field_name: cell_value}}
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {tat}",
            },
            method="PATCH",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.loads(r.read().decode("utf-8"))
        return body.get("code") == 0
    except Exception as exc:
        logger.debug("bitable writeback failed: %s", exc)
        return False
