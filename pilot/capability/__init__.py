"""Capability 层 — 工具 / Skills / Workforce / MCP 客户端.

边界:
  - 不直接处理用户输入（那是 Surface 层的事）
  - 不持有 session 状态（那是 Runtime 层的事）
  - 仅暴露纯函数 / 类供 Runtime 调用
"""

from pilot.capability.tools.registry import ToolRegistry, default_registry  # noqa: F401

__all__ = ["ToolRegistry", "default_registry"]
