"""V1.5 — Agent-Pilot 反向 MCP server（HTTP + SSE，端口 8003）.

目的:
  把 Agent-Pilot 的核心工具反向暴露给 Cursor / Claude Desktop / Trae 等外部 AI client，
  评委可在自己的 IDE 里直接调用我们的工具，作为差异化展示点。

为什么不用完整 MCP SDK?
  - mcp 官方包的 SSE/streamable 协议改动频繁，绑死特定版本反而脆弱；
  - 这里实现 HTTP/JSON 子集 + 心跳 SSE，兼容 Cursor 0.x 的 SSE transport；
  - 完整协议升级时只改本文件即可。

公开 4 个核心工具（不暴露 destructive 工具）:
  - pilot.doc.create / pilot.doc.append
  - pilot.slide.generate
  - pilot.web.search

启动:
    python -m pilot mcp                # 用 pilot CLI（如已注册）
    python -c "from pilot.surface.lark_mcp_runner import run; run()"
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger("pilot.surface.lark_mcp_runner")


EXPOSED_TOOLS = {
    "doc.create": "创建飞书 Docx 文档",
    "doc.append": "向 Docx 追加 LLM 自动生成的 Markdown 内容",
    "slide.generate": "基于上游文档生成 .pptx 演示稿 + Slidev md + 演讲稿",
    "web.search": "联网搜索（DDG + Bing CN 兜底）",
}


def _filter_tools_for_mcp(specs):
    """只暴露 EXPOSED_TOOLS 集合里的工具，避免外部 client 误调 destructive 工具."""
    return [s for s in specs if s.name in EXPOSED_TOOLS]


def create_app():
    from fastapi import Body, FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse

    app = FastAPI(
        title="Agent-Pilot V1.5 · 反向 MCP Server",
        description="Reverse MCP — 把 Agent-Pilot 核心工具暴露给 Cursor/Claude Desktop/Trae",
        version="1.5.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def index():
        return {
            "name": "Agent-Pilot V1.5 MCP Server",
            "version": "1.5.0",
            "protocol": "MCP-compatible HTTP+SSE subset",
            "exposed_tools": list(EXPOSED_TOOLS.keys()),
            "endpoints": {
                "tools_list": "GET /tools/list",
                "tools_call": "POST /tools/call",
                "sse": "GET /sse",
                "health": "GET /health",
            },
            "client_config_hint": (
                "在 Cursor 的 ~/.cursor/mcp.json 加：\n"
                '  {"mcpServers":{"agent-pilot":{"url":"http://<host>:8003/sse"}}}'
            ),
        }

    @app.get("/health")
    async def health():
        return {"status": "healthy", "ts": int(time.time())}

    @app.get("/tools/list")
    @app.post("/tools/list")
    async def tools_list():
        from pilot.capability.tools.registry import default_registry

        specs = _filter_tools_for_mcp(default_registry().list_specs())
        return {
            "tools": [
                {
                    "name": s.name,
                    "description": s.description,
                    "inputSchema": s.input_schema,
                }
                for s in specs
            ]
        }

    @app.post("/tools/call")
    async def tools_call(body: dict = Body(...)):
        name = body.get("name", "")
        args = body.get("arguments") or body.get("args") or {}

        if name not in EXPOSED_TOOLS:
            return JSONResponse(
                {
                    "isError": True,
                    "content": [{"type": "text", "text": f"工具 {name} 未暴露给 MCP（白名单：{list(EXPOSED_TOOLS.keys())}）"}],
                },
                status_code=400,
            )

        try:
            from pilot.capability.tools.registry import default_registry

            result = await default_registry().execute(
                tool_name=name,
                tool_input=args,
                ctx={"_via_mcp": True},
            )
        except Exception as e:
            logger.exception("MCP tools/call %s failed", name)
            return JSONResponse(
                {"isError": True, "content": [{"type": "text", "text": str(e)}]},
                status_code=200,
            )

        return {
            "isError": False,
            "content": [{"type": "json", "json": result}],
        }

    @app.get("/sse")
    async def sse(request: Request):
        """Cursor / Claude Desktop 的 SSE transport 兼容端点.

        - 客户端 GET /sse 后，server 周期性 emit `event: ping`，保持连接
        - 客户端 POST /messages 写入指令；这里简化为只支持 `tools/list` 和 `tools/call`
        - 真完整的 MCP 双向消息建议升级到 streamable HTTP（Cursor 1.x 默认）
        """

        async def gen():
            yield "event: ready\ndata: {\"server\":\"agent-pilot-mcp\",\"version\":\"1.5.0\"}\n\n"
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    yield f"event: ping\ndata: {json.dumps({'ts': int(time.time())})}\n\n"
                    await asyncio.sleep(15)
            except asyncio.CancelledError:
                return

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/messages")
    async def messages(body: dict = Body(...)):
        """SSE 反向通道：客户端 POST 调用工具/列表，server 直接 JSON 回复.

        简化协议（不是完整 MCP JSON-RPC 2.0），适合 demo 演示。
        """
        method = body.get("method", "")

        if method == "tools/list":
            from pilot.capability.tools.registry import default_registry

            specs = _filter_tools_for_mcp(default_registry().list_specs())
            return {
                "jsonrpc": "2.0",
                "id": body.get("id", 0),
                "result": {
                    "tools": [
                        {"name": s.name, "description": s.description, "inputSchema": s.input_schema}
                        for s in specs
                    ]
                },
            }

        if method == "tools/call":
            params = body.get("params") or {}
            name = params.get("name", "")
            args = params.get("arguments", {})
            if name not in EXPOSED_TOOLS:
                return {
                    "jsonrpc": "2.0",
                    "id": body.get("id", 0),
                    "error": {"code": -32601, "message": f"tool not exposed: {name}"},
                }
            from pilot.capability.tools.registry import default_registry

            try:
                result = await default_registry().execute(
                    tool_name=name, tool_input=args, ctx={"_via_mcp": True},
                )
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": body.get("id", 0),
                    "error": {"code": -32603, "message": str(e)[:200]},
                }
            return {
                "jsonrpc": "2.0",
                "id": body.get("id", 0),
                "result": {"content": [{"type": "json", "json": result}], "isError": False},
            }

        return {
            "jsonrpc": "2.0",
            "id": body.get("id", 0),
            "error": {"code": -32601, "message": f"unknown method: {method}"},
        }

    return app


def run(*, host: str = "0.0.0.0", port: int = 8003) -> None:
    import uvicorn

    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")
