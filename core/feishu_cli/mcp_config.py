"""Feishu MCP (Model Context Protocol) server configuration.

When deployed with lark-openapi-mcp (https://github.com/larksuite/lark-openapi-mcp),
Agent-Pilot can invoke Feishu APIs through a standardized MCP protocol.

This module provides:
- MCP server config for lark-openapi
- All 22 Feishu CLI skill definitions with actual commands
- A subprocess-based CLI runner with timeout and error handling
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
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

# ---------------------------------------------------------------------------
# All 22 Feishu CLI Skills
# ---------------------------------------------------------------------------

FEISHU_CLI_SKILLS: Dict[str, Dict[str, Any]] = {
    "lark-im": {
        "description": "消息与群组管理",
        "commands": [
            "lark-cli im send --chat-id {chat_id} --text {text}",
            "lark-cli im list-messages --chat-id {chat_id} --limit {limit}",
            "lark-cli im create-group --name {name} --members {members}",
        ],
    },
    "lark-doc": {
        "description": "云文档操作",
        "commands": [
            "lark-cli doc create --title {title} --folder {folder_token}",
            "lark-cli doc get --token {doc_token}",
            "lark-cli doc update --token {doc_token} --content {content}",
        ],
    },
    "lark-sheets": {
        "description": "电子表格操作",
        "commands": [
            "lark-cli sheets read --token {token} --range {range}",
            "lark-cli sheets write --token {token} --range {range} --values {values}",
        ],
    },
    "lark-calendar": {
        "description": "日历管理",
        "commands": [
            "lark-cli calendar list-events --start {start} --end {end}",
            "lark-cli calendar create-event --title {title} --start {start} --end {end}",
        ],
    },
    "lark-base": {
        "description": "多维表格",
        "commands": [
            "lark-cli base list-records --app-token {app_token} --table-id {table_id}",
            "lark-cli base add-record --app-token {app_token} --table-id {table_id} --fields {fields}",
            "lark-cli base create-table --app-token {app_token} --name {name}",
        ],
    },
    "lark-task": {
        "description": "任务管理",
        "commands": [
            "lark-cli task create --title {title} --due {due}",
            "lark-cli task list --status {status}",
        ],
    },
    "lark-drive": {
        "description": "云空间/文件管理",
        "commands": [
            "lark-cli drive upload --file {file_path} --folder {folder_token}",
            "lark-cli drive list --folder {folder_token}",
            "lark-cli drive create-folder --name {name} --parent {parent_token}",
        ],
    },
    "lark-wiki": {
        "description": "知识库",
        "commands": [
            "lark-cli wiki search --query {query} --space-id {space_id}",
            "lark-cli wiki create-space --name {name}",
        ],
    },
    "lark-contact": {
        "description": "通讯录",
        "commands": [
            "lark-cli contact search --query {query}",
            "lark-cli contact get-user --user-id {user_id}",
        ],
    },
    "lark-mail": {
        "description": "邮箱",
        "commands": [
            "lark-cli mail send --to {to} --subject {subject} --body {body}",
        ],
    },
    "lark-vc": {
        "description": "视频会议",
        "commands": [
            "lark-cli vc create --topic {topic} --start {start}",
        ],
    },
    "lark-minutes": {
        "description": "妙记",
        "commands": [
            "lark-cli minutes get --minute-token {token}",
        ],
    },
    "lark-approval": {
        "description": "审批流程",
        "commands": [
            "lark-cli approval create-instance --code {approval_code} --form {form_data}",
            "lark-cli approval get --instance-id {instance_id}",
        ],
    },
    "lark-attendance": {
        "description": "考勤打卡",
        "commands": [
            "lark-cli attendance get-records --user-ids {user_ids} --date {date}",
        ],
    },
    "lark-board": {
        "description": "白板",
        "commands": [
            "lark-cli board create --title {title}",
        ],
    },
    "lark-helpdesk": {
        "description": "服务台",
        "commands": [
            "lark-cli helpdesk create-ticket --summary {summary} --description {description}",
        ],
    },
    "lark-search": {
        "description": "搜索",
        "commands": [
            "lark-cli search universal --query {query} --scope {scope}",
        ],
    },
    "lark-openplatform": {
        "description": "开放平台",
        "commands": [
            "lark-cli openplatform get-app-info --app-id {app_id}",
        ],
    },
    "lark-bitable": {
        "description": "多维表格（高级）",
        "commands": [
            "lark-cli bitable create-table --app-token {app_token} --name {name}",
            "lark-cli bitable add-record --app-token {app_token} --table-id {table_id} --fields {fields}",
        ],
    },
    "lark-docx": {
        "description": "新版文档",
        "commands": [
            "lark-cli docx create --title {title} --folder {folder_token}",
            "lark-cli docx get --document-id {document_id}",
        ],
    },
    "lark-slides": {
        "description": "幻灯片",
        "commands": [
            "lark-cli slides create --title {title}",
        ],
    },
    "lark-lingo": {
        "description": "词典",
        "commands": [
            "lark-cli lingo search --query {query}",
        ],
    },
}


# ---------------------------------------------------------------------------
# CLI availability check
# ---------------------------------------------------------------------------


def _get_cli_path() -> str:
    try:
        from config import Config
        return getattr(Config, "LARK_CLI_PATH", "lark-cli")
    except Exception:
        return os.getenv("LARK_CLI_PATH", "lark-cli")


def _get_cli_timeout() -> int:
    try:
        from config import Config
        return getattr(Config, "LARK_CLI_TIMEOUT", 30)
    except Exception:
        return int(os.getenv("LARK_CLI_TIMEOUT", "30"))


def is_mcp_available() -> bool:
    return bool(shutil.which("npx") and os.getenv("FEISHU_APP_ID"))


def is_cli_available() -> bool:
    cli = _get_cli_path()
    return bool(shutil.which(cli))


# ---------------------------------------------------------------------------
# CLI runner with subprocess, timeout, and structured error handling
# ---------------------------------------------------------------------------


def run_cli_command(
    command_template: str,
    params: Dict[str, str],
    *,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute a Feishu CLI command via subprocess.

    Args:
        command_template: Command template with {placeholders}.
        params: Dict of placeholder values to substitute.
        timeout: Override default timeout (seconds).

    Returns:
        Dict with ok/stdout/stderr/return_code keys.
    """
    cli_path = _get_cli_path()
    if timeout is None:
        timeout = _get_cli_timeout()

    try:
        formatted = command_template.format(**params)
    except KeyError as e:
        return {
            "ok": False,
            "error": "missing_param",
            "message": f"Missing required parameter: {e}",
        }

    if cli_path != "lark-cli":
        formatted = formatted.replace("lark-cli", cli_path, 1)

    cmd_parts = shlex.split(formatted)

    env = os.environ.copy()
    for key in ("FEISHU_APP_ID", "FEISHU_APP_SECRET"):
        val = os.getenv(key, "")
        if val:
            env[key] = val

    try:
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "return_code": result.returncode,
            "command": formatted,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "timeout",
            "message": f"Command timed out after {timeout}s: {formatted}",
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "error": "cli_not_found",
            "message": f"CLI executable not found: {cli_path}",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": "execution_error",
            "message": str(e),
        }


# ---------------------------------------------------------------------------
# MCP tool descriptors
# ---------------------------------------------------------------------------


def get_mcp_tools() -> List[Dict[str, Any]]:
    """Return MCP-compatible tool descriptors for all Feishu CLI skills."""
    tools: List[Dict[str, Any]] = []
    cli_ok = is_cli_available()
    mcp_ok = is_mcp_available()

    for skill_id, skill in FEISHU_CLI_SKILLS.items():
        tools.append({
            "name": skill_id,
            "description": skill["description"],
            "source": "feishu-cli",
            "available": cli_ok or mcp_ok,
            "commands": skill["commands"],
        })

    return tools


def get_skill_by_name(skill_name: str) -> Optional[Dict[str, Any]]:
    """Look up a skill by its ID (e.g. 'lark-im')."""
    return FEISHU_CLI_SKILLS.get(skill_name)


def list_skill_names() -> List[str]:
    """Return all skill IDs."""
    return list(FEISHU_CLI_SKILLS.keys())


def get_all_commands() -> List[str]:
    """Return a flat list of every CLI command template."""
    commands: List[str] = []
    for skill in FEISHU_CLI_SKILLS.values():
        commands.extend(skill["commands"])
    return commands
