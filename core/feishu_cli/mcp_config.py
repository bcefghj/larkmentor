"""Feishu MCP (Model Context Protocol) server configuration.

When deployed with lark-openapi-mcp (https://github.com/larksuite/lark-openapi-mcp),
Agent-Pilot can invoke Feishu APIs through a standardized MCP protocol.

This module provides the MCP server config and a helper to check availability.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pilot.feishu_cli.mcp")

MCP_SERVER_CONFIG = {
    "name": "lark-openapi",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@anthropic-ai/mcp-proxy", "--", "lark-openapi-mcp"],
    "env": {
        "FEISHU_APP_ID": os.getenv("FEISHU_APP_ID", ""),
        "FEISHU_APP_SECRET": os.getenv("FEISHU_APP_SECRET", ""),
    },
}

FEISHU_CLI_SKILLS = [
    "calendar.create_event",
    "calendar.list_events",
    "docx.create_document",
    "docx.get_document",
    "im.send_message",
    "im.list_messages",
    "drive.create_folder",
    "drive.upload_file",
    "bitable.create_table",
    "bitable.add_record",
    "approval.create_instance",
    "wiki.create_space",
    "contact.get_user",
    "attendance.get_records",
    "vc.create_meeting",
    "task.create_task",
    "board.create_whiteboard",
    "sheets.create_spreadsheet",
    "sheets.write_range",
    "minutes.get_transcript",
    "helpdesk.create_ticket",
    "mail.send_mail",
    "openplatform.get_app_info",
    "search.universal_search",
]


def is_mcp_available() -> bool:
    import shutil
    return bool(shutil.which("npx") and os.getenv("FEISHU_APP_ID"))


def get_mcp_tools() -> List[Dict[str, Any]]:
    return [
        {"name": skill, "source": "feishu-mcp", "available": is_mcp_available()}
        for skill in FEISHU_CLI_SKILLS
    ]
