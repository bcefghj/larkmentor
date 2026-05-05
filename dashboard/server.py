"""Agent-Pilot Dashboard – FastAPI realtime monitoring server (v12 refactored).

Routes are split into ``dashboard/routes/`` submodules; middleware lives in
``dashboard/middleware.py``.  This file is the composition root that wires
everything together.

Run:
    uvicorn dashboard.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import time
import uuid as _uuid
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA_DIR = ROOT / "data"
STATIC_DIR = Path(__file__).parent / "static"

from config import Config

try:
    from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from starlette.responses import StreamingResponse
except ImportError as e:
    raise RuntimeError("Install fastapi & uvicorn: pip install fastapi uvicorn") from e

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app):
    app.state.start_ts = time.time()
    asyncio.create_task(_broadcast_loop())
    yield


app = FastAPI(
    title="Agent-Pilot API",
    description="Agent-Pilot v12 · 从 IM 对话到演示稿的一键智能闭环",
    version=Config.VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ──
_cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
_cors_origins = [o.strip() for o in _cors_origins if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials="*" not in _cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Middleware (extracted) ──
from dashboard.middleware import OptionalAPIKeyMiddleware, RequestIDMiddleware, rate_limit_middleware

app.middleware("http")(rate_limit_middleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(OptionalAPIKeyMiddleware)

# ── Observability (optional) ──
try:
    from core.observability import install_fastapi as _install_obs
    _install_obs(app)
except Exception:
    pass

# ── Route modules (extracted) ──
from dashboard.routes.health import router as _health_router
from dashboard.routes.pilot import router as _pilot_router
from dashboard.routes.legacy import router as _legacy_router

app.include_router(_health_router)
app.include_router(_pilot_router)
app.include_router(_legacy_router)

# ── v7 Pilot routes (optional) ──
try:
    from dashboard.api_v7 import install_v7_routes
    install_v7_routes(app)
except Exception:
    pass

# ── Mentor stats (optional) ──
try:
    from dashboard.mentor_stats import register as _register_mentor_stats
    _register_mentor_stats(app)
except Exception:
    pass

# ----- runtime state -----
DEMO_MODE = False
WS_CLIENTS: List[WebSocket] = []


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _decisions() -> List[Dict[str, Any]]:
    return _read_json(DATA_DIR / "decision_log.json", [])


def _profiles() -> Dict[str, Dict[str, Any]]:
    return _read_json(DATA_DIR / "sender_profiles.json", {})


def _user_states() -> Dict[str, Any]:
    return _read_json(DATA_DIR / "user_states.json", {})


# ----- demo data generator -----

def _demo_overview() -> Dict[str, Any]:
    return {
        "decisions_today": 142, "p0_today": 8, "p1_today": 24,
        "p2_today": 45, "p3_today": 65, "auto_replied": 45,
        "archived": 65, "active_users": 6, "in_focus_now": 3,
        "circuit_breakers_today": 1, "llm_call_rate": 0.108,
        "accuracy_rate": 0.99, "uptime_hours": 168.5,
        "mode": "demo", "ts": int(time.time()),
    }


def _demo_decisions(limit: int = 30) -> List[Dict[str, Any]]:
    senders = ["陈总监", "李 PM", "王同事", "TestBot", "财务系统",
               "客户张总", "运营小赵", "上级 CTO", "陌生人 X", "HR 系统"]
    summaries = ["线上故障 RCA 立刻处理", "今天会议改时间", "Q3 方案数据怎么取",
                 "周报记得交", "今天天气真好", "明天面试时间确认",
                 "增长方案第二版出了", "本周市场周报", "请教 SQL 写法",
                 "30 分钟内能给答复吗"]
    levels = ["P0"] * 1 + ["P1"] * 3 + ["P2"] * 5 + ["P3"] * 8
    out = []
    now = int(time.time())
    for i in range(limit):
        out.append({
            "decision_id": f"dec_{i:08x}",
            "sender_name": random.choice(senders),
            "level": random.choice(levels),
            "score": round(random.uniform(0.05, 0.95), 3),
            "summary": random.choice(summaries),
            "ts": now - i * random.randint(60, 300),
            "rolled_back": random.random() < 0.05,
        })
    return out


def _demo_profiles(limit: int = 10) -> List[Dict[str, Any]]:
    names = ["陈总监", "李 PM", "王同事", "财务", "客户张总",
             "运营小赵", "上级 CTO", "HR", "TestBot", "陌生人 X"]
    out = []
    for i in range(min(limit, len(names))):
        out.append({
            "sender_id": f"u_{i:06x}", "sender_name": names[i],
            "identity_tag": random.choice(["superior", "peer", "vip", "occasional", "bot"]),
            "relation_strength": round(random.uniform(0.1, 0.95), 2),
            "msg_count_total": random.randint(10, 500),
            "user_responded_count": random.randint(0, 50),
            "importance_bias": round(random.uniform(-0.2, 0.3), 2),
        })
    return out


def _demo_heatmap() -> List[List[int]]:
    rows = []
    for d in range(7):
        row = []
        for h in range(24):
            base = 0
            if 9 <= h <= 18:
                base = random.randint(3, 12)
            if 14 <= h <= 16:
                base += random.randint(2, 6)
            row.append(base)
        rows.append(row)
    return rows


# ----- aggregation from real data -----

def _real_overview() -> Dict[str, Any]:
    decisions = _decisions() if isinstance(_decisions(), list) else []
    today_start = int(time.time()) - 86400
    today = [d for d in decisions if isinstance(d, dict) and d.get("ts", 0) >= today_start]
    counts = Counter(d.get("level", "P3") for d in today)
    raw_states = _user_states()
    states = raw_states if isinstance(raw_states, dict) else {}
    in_focus = sum(
        1 for u in states.values()
        if isinstance(u, dict) and isinstance(u.get("focus_mode"), dict) and u["focus_mode"].get("enabled")
    )
    return {
        "decisions_today": len(today),
        "p0_today": counts.get("P0", 0), "p1_today": counts.get("P1", 0),
        "p2_today": counts.get("P2", 0), "p3_today": counts.get("P3", 0),
        "auto_replied": counts.get("P2", 0), "archived": counts.get("P3", 0),
        "active_users": len(states), "in_focus_now": in_focus,
        "circuit_breakers_today": sum(1 for d in today if d.get("circuit_breaker_triggered")),
        "llm_call_rate": round(sum(1 for d in today if d.get("llm_used")) / max(1, len(today)), 3),
        "accuracy_rate": 0.99,
        "uptime_hours": round((time.time() - app.state.start_ts) / 3600, 1),
        "mode": "live", "ts": int(time.time()),
    }


def _real_heatmap() -> List[List[int]]:
    raw = _decisions()
    decisions = raw if isinstance(raw, list) else []
    grid = [[0] * 24 for _ in range(7)]
    now = time.time()
    for d in decisions:
        if not isinstance(d, dict):
            continue
        ts = d.get("ts", 0)
        if ts < now - 7 * 86400:
            continue
        days_ago = int((now - ts) // 86400)
        if days_ago >= 7:
            continue
        hour = time.localtime(ts).tm_hour
        grid[6 - days_ago][hour] += 1
    return grid


# ----- core routes (kept in server.py for state access) -----

@app.get("/", response_class=HTMLResponse)
async def index():
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return idx.read_text(encoding="utf-8")
    return "<h1>Agent-Pilot Dashboard</h1><p>Static UI not built. See dashboard/static/index.html</p>"


@app.get("/api/overview")
async def overview():
    return _demo_overview() if DEMO_MODE else _real_overview()


@app.get("/api/decisions")
async def decisions(limit: int = Query(30, ge=1, le=200)):
    if DEMO_MODE:
        return _demo_decisions(limit)
    raw = _decisions()
    out = [d for d in raw if isinstance(d, dict)] if isinstance(raw, list) else []
    return sorted(out, key=lambda d: d.get("ts", 0), reverse=True)[:limit]


@app.get("/api/profiles")
async def profiles(limit: int = Query(10, ge=1, le=100)):
    if DEMO_MODE:
        return _demo_profiles(limit)
    raw = _profiles()
    if not isinstance(raw, dict):
        raw = {}
    items = []
    for sid, p in raw.items():
        if not isinstance(p, dict):
            continue
        items.append({
            "sender_id": sid, "sender_name": p.get("name", sid[-8:]),
            "identity_tag": p.get("identity_tag", "unknown"),
            "relation_strength": round(p.get("relation_strength", 0.0), 2),
            "msg_count_total": p.get("msg_count_total", 0),
            "user_responded_count": p.get("user_responded_count", 0),
            "importance_bias": round(p.get("importance_bias", 0.0), 2),
        })
    items.sort(key=lambda x: x["msg_count_total"], reverse=True)
    return items[:limit]


@app.get("/api/heatmap")
async def heatmap():
    return {"grid": _demo_heatmap() if DEMO_MODE else _real_heatmap()}


@app.get("/api/users")
async def users():
    if DEMO_MODE:
        return [
            {"user_id": f"u_demo_{i}",
             "name": ["李洁盈", "戴尚好", "评委 A", "评委 B", "测试用户"][i],
             "in_focus": i % 2 == 0, "tasks": random.randint(0, 4),
             "pending_msgs": random.randint(0, 12)}
            for i in range(5)
        ]
    raw_states = _user_states()
    states = raw_states if isinstance(raw_states, dict) else {}
    out = []
    for uid, s in states.items():
        if not isinstance(s, dict):
            continue
        fm = s.get("focus_mode", {}) if isinstance(s.get("focus_mode"), dict) else {}
        out.append({
            "user_id": uid, "name": s.get("name", uid[-8:]),
            "in_focus": fm.get("enabled", False),
            "tasks": len(s.get("tasks", [])),
            "pending_msgs": len(s.get("pending_msgs", [])),
        })
    return out


# ── /api/v1 mirrors ──

@app.get("/api/v1/overview")
async def v1_overview():
    return await overview()


@app.get("/api/v1/decisions")
async def v1_decisions(limit: int = Query(30, ge=1, le=200)):
    return await decisions(limit)


@app.get("/api/v1/profiles")
async def v1_profiles(limit: int = Query(10, ge=1, le=100)):
    return await profiles(limit)


@app.get("/api/v1/heatmap")
async def v1_heatmap():
    return await heatmap()


@app.get("/api/v1/users")
async def v1_users():
    return await users()


@app.get("/demo")
async def to_demo():
    global DEMO_MODE
    DEMO_MODE = True
    return {"mode": "demo"}


@app.get("/live")
async def to_live():
    global DEMO_MODE
    DEMO_MODE = False
    return {"mode": "live"}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    WS_CLIENTS.append(ws)
    try:
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        if ws in WS_CLIENTS:
            WS_CLIENTS.remove(ws)


async def _broadcast_loop():
    while True:
        await asyncio.sleep(5)
        if not WS_CLIENTS:
            continue
        payload = {"type": "tick", "overview": _demo_overview() if DEMO_MODE else _real_overview()}
        msg = json.dumps(payload, ensure_ascii=False)
        dead = []
        for ws in WS_CLIENTS:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for d in dead:
            if d in WS_CLIENTS:
                WS_CLIENTS.remove(d)


# ── SSE Streaming Endpoint ──

@app.get("/api/pilot/stream/{plan_id}")
async def pilot_stream_sse(plan_id: str):
    async def _event_generator():
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

        def _on_msg(payload: Dict[str, Any]) -> None:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass

        try:
            from core.sync.crdt_hub import default_hub
            hub = default_hub()
        except Exception:
            yield f"data: {json.dumps({'error': 'crdt_hub_unavailable'})}\n\n"
            return

        client_id = f"sse_{plan_id}_{_uuid.uuid4().hex[:8]}"
        hub.subscribe(client_id, _on_msg)
        history = hub.join(client_id, plan_id)
        try:
            for evt in history:
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    ev = payload.get("event") or payload.get("state") or {}
                    if isinstance(ev, dict) and ev.get("type") == "plan_done":
                        break
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            hub.leave(client_id, plan_id)
            hub.unsubscribe(client_id)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── DAG Visualization (template served from static file or inline fallback) ──

@app.get("/v12/dag/{plan_id}", response_class=HTMLResponse)
@app.get("/v11/dag/{plan_id}", response_class=HTMLResponse)
@app.get("/v10/dag/{plan_id}", response_class=HTMLResponse)
async def dag_visualization(plan_id: str):
    dag_page = STATIC_DIR / "dag.html"
    if dag_page.exists():
        return dag_page.read_text(encoding="utf-8").replace("{{PLAN_ID}}", plan_id)
    return f"<h1>DAG Visualization for {plan_id}</h1><p>Static page not built.</p>"


@app.get("/v12/dashboard", response_class=HTMLResponse)
@app.get("/v11/dashboard", response_class=HTMLResponse)
@app.get("/dashboard/pilot", response_class=HTMLResponse)
@app.get("/pilot", response_class=HTMLResponse)
async def pilot_dashboard_page():
    page = STATIC_DIR / "pilot.html"
    if page.exists():
        return page.read_text(encoding="utf-8")
    return f"<h1>Agent-Pilot v12 Dashboard</h1><p>Static UI not built yet.</p>"


@app.get("/pilot/{plan_id}", response_class=HTMLResponse)
async def pilot_share_view(plan_id: str):
    page = STATIC_DIR / "pilot_share.html"
    if page.exists():
        return page.read_text(encoding="utf-8").replace("{{PLAN_ID}}", plan_id)
    return f"<h1>Pilot Plan {plan_id}</h1><p>Share page not built.</p>"


# ── Offline merge ──

@app.get("/api/sync/reconcile/{room}")
async def sync_reconcile(room: str):
    try:
        from core.sync.offline_merge import reconcile
        return reconcile(room)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Mount sync router (optional) ──
try:
    from core.sync.ws_server import router as _sync_router
    if _sync_router is not None:
        app.include_router(_sync_router)
except Exception:
    pass

# ── Artifacts ──
ARTIFACT_DIR = ROOT / "data" / "pilot_artifacts"
try:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/artifacts", StaticFiles(directory=str(ARTIFACT_DIR)), name="artifacts")
except Exception:
    pass

# ── Static mount ──
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
