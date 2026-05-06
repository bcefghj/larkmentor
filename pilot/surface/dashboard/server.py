"""Web Dashboard — FastAPI 实时监控.

路由:
  /                       → 主页（动画 UI）
  /dashboard              → 仪表盘
  /multi-end              → 多端同步监控
  /api/sessions           → list sessions
  /api/sessions/{id}      → session 详情
  /api/events/{id}        → 事件流（SSE）
  /artifacts/...          → 静态产物（pptx / md / canvas）
  /docs                   → API 文档
  /metrics                → Prometheus / OpenTelemetry
  /ws                     → WebSocket 状态广播
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("pilot.surface.dashboard.server")

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data"))).resolve()
STATIC_DIR = Path(__file__).parent / "static"


def create_app():
    from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.middleware.cors import CORSMiddleware
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        app.state.start_ts = time.time()
        app.state.ws_clients = []
        yield

    app = FastAPI(
        title="Agent-Pilot V1",
        description="飞书 IM 中的 AI 主驾驶 Harness",
        version="1.0.0",
        docs_url="/docs",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── 健康 ──
    @app.get("/health")
    async def health():
        return {
            "status": "healthy",
            "version": "v1.0.0",
            "uptime_sec": round(time.time() - app.state.start_ts, 1),
            "data_dir": str(DATA_DIR),
        }

    # ── 主页 ──
    @app.get("/", response_class=HTMLResponse)
    async def index():
        f = STATIC_DIR / "index.html"
        if f.exists():
            return f.read_text(encoding="utf-8")
        return _fallback_index()

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(plan_id: str = ""):
        f = STATIC_DIR / "dashboard.html"
        content = f.read_text(encoding="utf-8") if f.exists() else _fallback_dashboard(plan_id)
        return content.replace("{{PLAN_ID}}", plan_id)

    @app.get("/multi-end", response_class=HTMLResponse)
    async def multi_end():
        f = STATIC_DIR / "multi_end.html"
        if f.exists():
            return f.read_text(encoding="utf-8")
        return _fallback_multi_end()

    # ── API ──
    @app.get("/api/sessions")
    async def list_sessions(limit: int = Query(20, ge=1, le=100)):
        from pilot.runtime.checkpoint import list_sessions

        return list_sessions(limit=limit)

    @app.get("/api/sessions/{session_id}")
    async def session_detail(session_id: str):
        from pilot.runtime.checkpoint import load_session

        s = load_session(session_id)
        if not s:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return s

    @app.get("/api/events/{session_id}")
    async def event_stream(session_id: str):
        """SSE 事件流（前端 EventSource 订阅）."""
        from pilot.context.event_log import EventLog

        async def gen():
            log = EventLog(session_id)
            offset = 0
            while True:
                events = log.read_all()
                new = events[offset:]
                for evt in new:
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                offset = len(events)
                await asyncio.sleep(1.0)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ── 工具/Skill 元信息 ──
    @app.get("/api/tools")
    async def list_tools():
        from pilot.capability.tools.registry import default_registry

        reg = default_registry()
        return [
            {
                "name": s.name,
                "description": s.description,
                "read_only": s.read_only,
                "namespace": s.namespace,
                "input_schema": s.input_schema,
            }
            for s in reg.list_specs()
        ]

    # ── WebSocket（基础心跳）──
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        app.state.ws_clients.append(ws)
        try:
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_text("pong")
        except WebSocketDisconnect:
            if ws in app.state.ws_clients:
                app.state.ws_clients.remove(ws)

    # ── Sync Hub WebSocket ──
    @app.websocket("/sync/ws/{room_id}")
    async def sync_ws(ws: WebSocket, room_id: str):
        from pilot.surface.sync.hub import default_hub

        hub = default_hub()
        await ws.accept()
        client_id = ""
        try:
            client_id = await hub.join(room_id=room_id, ws=ws)
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                kind = msg.get("kind", "")
                if kind == "publish":
                    await hub.publish(
                        room_id=room_id,
                        kind=msg.get("event_kind", "user_event"),
                        payload=msg.get("payload", {}),
                        from_client_id=client_id,
                    )
                elif kind == "yjs.update":
                    await hub.yjs_apply_update(
                        room_id=room_id,
                        update_b64=msg.get("update_b64", ""),
                        from_client_id=client_id,
                    )
                elif kind == "reconcile.request":
                    diff = await hub.reconcile(
                        room_id=room_id,
                        client_state_b64=msg.get("state_vector", ""),
                    )
                    await ws.send_text(json.dumps({
                        "kind": "reconcile.response",
                        "update_b64": diff,
                    }))
                elif kind == "ping":
                    await ws.send_text(json.dumps({"kind": "pong"}))
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning("sync ws error: %s", e)
        finally:
            if client_id:
                await hub.leave(room_id=room_id, client_id=client_id)

    @app.get("/api/sync/stats")
    async def sync_stats():
        from pilot.surface.sync.hub import default_hub
        return default_hub().stats()

    # ── Artifacts ──
    artifacts_dir = DATA_DIR / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/artifacts", StaticFiles(directory=str(artifacts_dir)), name="artifacts")

    # ── Static UI ──
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


def run(*, host: str = "0.0.0.0", port: int = 8001) -> None:
    import uvicorn

    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


# ── Fallback HTML（M8 会被替换为动画 UI）──


def _fallback_index() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>Agent-Pilot V1</title></head>
<body style="font-family: sans-serif; max-width: 800px; margin: 40px auto;">
<h1>🛫 Agent-Pilot V1</h1>
<p>飞书 IM 中的 AI 主驾驶 Harness</p>
<ul>
  <li><a href="/dashboard">仪表盘</a></li>
  <li><a href="/multi-end">多端协同</a></li>
  <li><a href="/docs">API 文档</a></li>
  <li><a href="/api/tools">工具清单</a></li>
  <li><a href="/api/sessions">最近 sessions</a></li>
  <li><a href="/health">健康检查</a></li>
</ul>
</body></html>"""


def _fallback_dashboard(plan_id: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Dashboard - {plan_id or "Agent-Pilot V1"}</title></head>
<body style="font-family: sans-serif; max-width: 1200px; margin: 20px auto;">
<h1>🛫 Agent-Pilot V1 仪表盘</h1>
<p>plan_id = <code>{{PLAN_ID}}</code></p>
<p>静态 UI 尚未构建（M8 将填充动画 UI）。</p>
<p>临时 API：<a href="/api/sessions">/api/sessions</a> · <a href="/api/tools">/api/tools</a></p>
</body></html>"""


def _fallback_multi_end() -> str:
    return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>多端协同 - Agent-Pilot V1</title></head>
<body style="font-family: sans-serif; max-width: 1200px; margin: 20px auto;">
<h1>🌐 多端协同实时监控</h1>
<p>静态 UI 尚未构建（M8 将填充 yjs-flutter + WebSocket 实时状态）。</p>
</body></html>"""
