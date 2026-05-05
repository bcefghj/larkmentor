"""Agent-Pilot MCP Server – stdio, SSE, and HTTP transports.

Implements the Model Context Protocol to expose Agent-Pilot tools to any
MCP-compatible client (Cursor, Claude Code, custom agents).

Transport matrix:
    stdio  →  official ``mcp`` SDK (preferred for IDE integrations)
    sse    →  FastMCP SSE (for network-accessible Cursor/Claude Code)
    http   →  lightweight JSON server (fallback when mcp SDK unavailable)

Authentication: shared-secret bearer token via ``AGENT_PILOT_MCP_SECRET``
env var. When set, every request must carry ``Authorization: Bearer <secret>``
(HTTP/SSE) or send an ``auth`` frame (stdio). When unset, auth is disabled.

Run::

    python -m core.mcp_server.server                          # stdio
    python -m core.mcp_server.server --transport sse          # SSE on :8765
    python -m core.mcp_server.server --transport http --port 9000  # plain HTTP
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

from .tools import (
    TOOL_REGISTRY,
    TOOL_SCHEMAS,
    call_tool,
    get_tool_schema,
    list_tools,
    to_json,
    _err,
)

logger = logging.getLogger("agent_pilot.mcp.server")

MCP_SERVER_NAME = "Agent-Pilot"
MCP_SERVER_VERSION = "2.0.0"


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def _get_secret() -> Optional[str]:
    return os.getenv("AGENT_PILOT_MCP_SECRET")


def _verify_auth(token: Optional[str]) -> bool:
    """Constant-time comparison of bearer token against configured secret."""
    secret = _get_secret()
    if not secret:
        return True  # auth disabled
    if not token:
        return False
    return hmac.compare_digest(secret.encode(), token.encode())


def _extract_bearer(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    parts = auth_header.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


# ---------------------------------------------------------------------------
# MCP proper (official SDK)
# ---------------------------------------------------------------------------


def _start_mcp_proper(transport: str, port: int, host: str) -> bool:
    """Start server via the official ``mcp`` SDK. Returns False if unavailable."""
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore[import-untyped]
    except Exception:
        logger.warning("mcp SDK not installed; falling back to JSON HTTP server")
        return False

    server = FastMCP(
        MCP_SERVER_NAME,
        version=MCP_SERVER_VERSION,
    )

    def _make_wrapper(name: str, fn, schema: Dict[str, Any]):
        """Create an async wrapper with correct signature for FastMCP."""

        async def wrapper(**kwargs: Any) -> Any:
            if _get_secret():
                auth_token = kwargs.pop("_auth_token", None)
                if not _verify_auth(auth_token):
                    return _err("auth_failed", "Invalid or missing authentication token")
            return fn(**kwargs)

        wrapper.__name__ = name
        wrapper.__doc__ = schema.get("description", "")
        return wrapper

    for name, (fn, doc, schema) in TOOL_REGISTRY.items():
        wrapper = _make_wrapper(name, fn, schema)
        server.tool(
            name=name,
            description=doc,
        )(wrapper)

    logger.info("Starting MCP server (%s transport) name=%s version=%s", transport, MCP_SERVER_NAME, MCP_SERVER_VERSION)

    if transport == "stdio":
        server.run("stdio")
    else:
        server.run("sse", host=host, port=port)
    return True


# ---------------------------------------------------------------------------
# Visual HTML page
# ---------------------------------------------------------------------------


def _render_visual_html() -> str:
    """Self-contained HTML that lists every MCP tool with try-it-live UI."""
    tools = list_tools()
    tools_json = json.dumps(tools, ensure_ascii=False)
    return (
        "<!doctype html>\n"
        "<html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{MCP_SERVER_NAME} · MCP Tools</title>"
        "<style>"
        ":root{--bg:#fafaf9;--bg2:#fff;--fg:#0a0a09;--fg2:#4a4a48;--line:#e7e7e4;"
        "--accent:#3370FF;--accent-soft:#e8f0ff}"
        "[data-theme='dark']{--bg:#0a0a09;--bg2:#131311;--fg:#f5f5f3;--fg2:#b9b9b3;"
        "--line:#2a2a27;--accent:#6699FF;--accent-soft:rgba(102,153,255,.12)}"
        "*{box-sizing:border-box;margin:0;padding:0}"
        "body{font-family:Inter,'PingFang SC',sans-serif;background:var(--bg);"
        "color:var(--fg);line-height:1.55;max-width:1100px;margin:0 auto;padding:2rem}"
        "h1{font-size:1.8rem;font-weight:800;margin-bottom:.5rem}"
        "h1 em{font-style:normal;color:var(--accent)}"
        "code{font-family:'JetBrains Mono',monospace;font-size:.85em}"
        ".grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));margin-top:1.5rem}"
        ".card{background:var(--bg2);border:1px solid var(--line);border-radius:10px;"
        "padding:14px;cursor:pointer;transition:.15s}"
        ".card:hover{border-color:var(--accent);transform:translateY(-2px)}"
        ".card .name{font-family:'JetBrains Mono',monospace;font-weight:700;"
        "font-size:.85rem;color:var(--accent)}"
        ".card .desc{margin-top:6px;font-size:.8rem;color:var(--fg2);line-height:1.5}"
        ".panel{margin-top:1.5rem;background:var(--bg2);border:1px solid var(--line);"
        "border-radius:10px;padding:16px}"
        "textarea{width:100%;min-height:100px;padding:10px;border:1px solid var(--line);"
        "border-radius:6px;font-family:'JetBrains Mono',monospace;font-size:.8rem;"
        "background:var(--bg);color:var(--fg);resize:vertical;margin-top:8px}"
        "button{padding:8px 16px;background:var(--accent);color:#fff;border:none;"
        "border-radius:6px;font-weight:600;cursor:pointer;margin-top:8px}"
        "pre{margin-top:10px;background:var(--bg);border:1px solid var(--line);"
        "border-radius:6px;padding:10px;font-family:'JetBrains Mono',monospace;"
        "font-size:.78rem;color:var(--fg2);white-space:pre-wrap;max-height:400px;overflow:auto}"
        "</style></head><body>"
        f"<h1>{MCP_SERVER_NAME} · <em>MCP Tools</em></h1>"
        f"<p style='color:var(--fg2);font-size:.9rem'>"
        f"{len(tools)} tools exposed via Model Context Protocol</p>"
        "<div class='grid' id='grid'></div>"
        "<div class='panel'>"
        "<strong>Try a tool</strong> · <code id='curName'>—</code>"
        "<textarea id='args'></textarea>"
        "<button id='run'>POST /mcp/call →</button>"
        "<pre id='result'>Select a tool above…</pre>"
        "</div>"
        "<script>"
        "var T=" + tools_json + ";"
        "var g=document.getElementById('grid');"
        "T.forEach(function(t){"
        "var c=document.createElement('div');c.className='card';"
        "c.innerHTML='<div class=\"name\">'+t.name+'</div><div class=\"desc\">'+t.description+'</div>';"
        "c.onclick=function(){"
        "document.getElementById('curName').textContent=t.name;"
        "var schema=t.inputSchema||{};"
        "var props=schema.properties||{};"
        "var ex={};"
        "Object.keys(props).forEach(function(k){"
        "if(props[k].default!==undefined)ex[k]=props[k].default;"
        "else if(props[k].type==='string')ex[k]='';"
        "else if(props[k].type==='integer')ex[k]=0;"
        "else if(props[k].type==='boolean')ex[k]=true;"
        "else if(props[k].type==='array')ex[k]=[];"
        "else if(props[k].type==='object')ex[k]={};"
        "});"
        "document.getElementById('args').value=JSON.stringify({tool:t.name,arguments:ex},null,2);"
        "};"
        "g.appendChild(c);"
        "});"
        "document.getElementById('run').onclick=function(){"
        "var body;try{body=JSON.parse(document.getElementById('args').value)}catch(e){"
        "document.getElementById('result').textContent='JSON parse error: '+e.message;return}"
        "fetch('/mcp/call',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify(body)}).then(r=>r.json()).then(j=>"
        "document.getElementById('result').textContent=JSON.stringify(j,null,2))"
        ".catch(e=>document.getElementById('result').textContent='Error: '+e.message)};"
        "</script></body></html>"
    )


# ---------------------------------------------------------------------------
# Fallback HTTP server
# ---------------------------------------------------------------------------


class _MCPHandler(BaseHTTPRequestHandler):
    """JSON HTTP adapter — works without the ``mcp`` SDK."""

    def _check_auth(self) -> bool:
        if not _get_secret():
            return True
        token = _extract_bearer(self.headers.get("Authorization"))
        if _verify_auth(token):
            return True
        self._json(401, _err("auth_failed", "Invalid or missing Bearer token"))
        return False

    def _json(self, status: int, payload: Any) -> None:
        body = to_json(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- GET ----------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")

        if path in ("", "/", "/mcp", "/visual", "/index.html"):
            self._html(200, _render_visual_html())
            return

        if path in ("/health", "/mcp/health"):
            self._json(
                200,
                {
                    "status": "ok",
                    "server": MCP_SERVER_NAME,
                    "version": MCP_SERVER_VERSION,
                    "tools_count": len(TOOL_REGISTRY),
                    "auth_required": bool(_get_secret()),
                    "ts": int(time.time()),
                },
            )
            return

        if path in ("/tools", "/mcp/tools", "/list_tools", "/mcp/tools.json"):
            if not self._check_auth():
                return
            self._json(
                200,
                {
                    "server": MCP_SERVER_NAME,
                    "version": MCP_SERVER_VERSION,
                    "tools": list_tools(),
                },
            )
            return

        if path.startswith("/mcp/schema/"):
            tool_name = path[len("/mcp/schema/") :]
            schema = get_tool_schema(tool_name)
            if schema:
                self._json(200, schema)
            else:
                self._json(404, _err("not_found", f"No schema for '{tool_name}'"))
            return

        self._json(404, _err("not_found", f"Unknown path: {self.path}"))

    # -- POST ---------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        if not self._check_auth():
            return

        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            self._json(400, _err("bad_json", "Request body is not valid JSON"))
            return

        path = self.path.split("?")[0].rstrip("/")

        if path in ("/call", "/mcp/call"):
            tool_name = body.get("tool") or body.get("name", "")
            args = body.get("arguments", {}) or body.get("params", {}) or {}
            if not tool_name:
                self._json(400, _err("missing_tool", "Request body must include 'tool' field"))
                return
            result = call_tool(tool_name, args)
            self._json(200, result)
            return

        # MCP JSON-RPC style (tools/call)
        if path in ("/mcp/tools/call", "/tools/call"):
            tool_name = body.get("name", "")
            args = body.get("arguments", {})
            if not tool_name:
                self._json(400, _err("missing_tool", "'name' field required"))
                return
            result = call_tool(tool_name, args)
            self._json(
                200,
                {
                    "content": [{"type": "text", "text": to_json(result)}],
                    "isError": bool(isinstance(result, dict) and result.get("error")),
                },
            )
            return

        self._json(404, _err("not_found", f"Unknown path: {self.path}"))

    # -- OPTIONS (CORS) -----------------------------------------------------

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        pass  # silence stdlib HTTP logging


def _start_http_server(host: str, port: int) -> None:
    httpd = ThreadingHTTPServer((host, port), _MCPHandler)
    auth_msg = " (auth ENABLED)" if _get_secret() else " (auth DISABLED)"
    logger.info(
        "%s MCP HTTP server listening on http://%s:%s%s",
        MCP_SERVER_NAME,
        host,
        port,
        auth_msg,
    )
    print(f"✓ {MCP_SERVER_NAME} MCP server running at http://{host}:{port}{auth_msg}", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()
        logger.info("Server stopped.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"{MCP_SERVER_NAME} MCP Server",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http"],
        default="stdio",
        help="stdio for MCP clients, sse for FastMCP, http for plain JSON",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    logger.info(
        "Starting %s v%s transport=%s host=%s port=%s tools=%d",
        MCP_SERVER_NAME,
        MCP_SERVER_VERSION,
        args.transport,
        args.host,
        args.port,
        len(TOOL_REGISTRY),
    )

    if args.transport == "stdio":
        if _start_mcp_proper("stdio", args.port, args.host):
            return 0
        logger.warning("stdio requires the mcp SDK; switching to HTTP")

    elif args.transport == "sse":
        if _start_mcp_proper("sse", args.port, args.host):
            return 0
        logger.warning("FastMCP unavailable; switching to HTTP fallback")

    _start_http_server(args.host, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
