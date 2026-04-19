"""FlowGuard MCP Server.

Exposes FlowGuard's intelligence (memory, classification, status) over the
Model Context Protocol so any MCP client (Cursor, Claude Code, OpenClaw,
custom Agent) can plug in without writing Feishu integration code.

Run as a stand-alone process::

    python -m core.mcp_server.server  # stdio transport
    python -m core.mcp_server.server --sse --port 8765  # SSE for Cursor

The protocol layer is intentionally optional – if the ``mcp`` package is
not installed, importing this module still succeeds and the rest of
FlowGuard runs unaffected.
"""

from .tools import TOOL_REGISTRY  # noqa: F401
