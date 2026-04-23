"""Thin client for the official Feishu remote MCP server.

Endpoint: ``https://mcp.feishu.cn/mcp`` (Streamable HTTP, JSON-RPC 2.0).

Usage
-----
Set one of (and ``FEISHU_MCP_ALLOWED_TOOLS`` to scope-limit):
    FEISHU_MCP_TAT                   – tenant_access_token (preferred)
    FEISHU_MCP_UAT                   – user_access_token (when acting as a user)

Then let the default MCPManager auto-register the server (see
``core.agent_pilot.harness.mcp_client.default_mcp_manager``).

This module is the high-level convenience facade that picks the right
tool for "create doc / append content / list calendar events" so callers
don't need to remember the MCP tool names.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("flowguard.feishu.remote_mcp")


def _mgr():
    try:
        from core.agent_pilot.harness.mcp_client import default_mcp_manager
        return default_mcp_manager()
    except Exception as exc:
        logger.debug("mcp manager unavailable: %s", exc)
        return None


def is_available() -> bool:
    mgr = _mgr()
    if mgr is None:
        return False
    return "feishu_remote" in mgr.list_aliases()


def call(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Call a Feishu official MCP tool. Returns result dict or ``{"error": ...}``."""
    mgr = _mgr()
    if mgr is None or "feishu_remote" not in mgr.list_aliases():
        return {"error": "feishu remote MCP not registered"}
    try:
        return mgr.dispatch("feishu_remote", tool_name, arguments or {})
    except Exception as exc:
        return {"error": str(exc)}


def doc_create(title: str, folder_token: str = "") -> Dict[str, Any]:
    """Create a Docx via the official MCP (preferred over raw API)."""
    args = {"title": title}
    if folder_token:
        args["folder_token"] = folder_token
    return call("docx.create_document", args)


def doc_append(doc_id: str, markdown: str) -> Dict[str, Any]:
    return call("docx.append_blocks", {"doc_id": doc_id, "markdown": markdown})


def calendar_list(user_id: str = "", days: int = 7) -> Dict[str, Any]:
    args = {"user_id": user_id, "range_days": days}
    return call("calendar.list_events", args)


def bitable_add_record(app_token: str, table_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    return call("bitable.add_record", {
        "app_token": app_token, "table_id": table_id, "fields": fields,
    })


def wiki_search(query: str, space_id: str = "") -> Dict[str, Any]:
    args = {"query": query}
    if space_id:
        args["space_id"] = space_id
    return call("wiki.search_nodes", args)
