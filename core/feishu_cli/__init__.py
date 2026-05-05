"""Feishu CLI integration layer.

Provides MCP server configuration for lark-openapi-mcp and helpers to
check availability and enumerate supported skills at runtime.
"""

from .mcp_config import (
    FEISHU_CLI_SKILLS,
    MCP_SERVER_CONFIG,
    get_mcp_tools,
    is_mcp_available,
)

__all__ = [
    "MCP_SERVER_CONFIG",
    "FEISHU_CLI_SKILLS",
    "is_mcp_available",
    "get_mcp_tools",
]
