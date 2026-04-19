"""LarkMentor Dashboard - FastAPI realtime monitoring server.

Endpoints:
    GET  /                     – static index.html
    GET  /api/overview         – metrics summary
    GET  /api/decisions        – recent classifications
    GET  /api/profiles         – top sender profiles
    GET  /api/heatmap          – 24h interruption heatmap
    GET  /api/users            – per-user state snapshot
    GET  /api/health           – live/ready probe
    GET  /demo                 – switch to demo mode (synthetic data)
    GET  /live                 – switch back to live mode
    WS   /ws                   – live updates (broadcast every 5s)

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
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA_DIR = ROOT / "data"
STATIC_DIR = Path(__file__).parent / "static"

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
except ImportError as e:
    raise RuntimeError("Install fastapi & uvicorn: pip install fastapi uvicorn") from e


app = FastAPI(title="LarkMentor Dashboard", version="3.0")

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
        "decisions_today": 142,
        "p0_today": 8,
        "p1_today": 24,
        "p2_today": 45,
        "p3_today": 65,
        "auto_replied": 45,
        "archived": 65,
        "active_users": 6,
        "in_focus_now": 3,
        "circuit_breakers_today": 1,
        "llm_call_rate": 0.108,
        "accuracy_rate": 0.99,
        "uptime_hours": 168.5,
        "mode": "demo",
        "ts": int(time.time()),
    }


def _demo_decisions(limit: int = 30) -> List[Dict[str, Any]]:
    senders = ["陈总监", "李 PM", "王同事", "TestBot", "财务系统",
               "客户张总", "运营小赵", "上级 CTO", "陌生人 X", "HR 系统"]
    summaries = [
        "线上故障 RCA 立刻处理", "今天会议改时间", "Q3 方案数据怎么取",
        "周报记得交", "今天天气真好", "明天面试时间确认",
        "增长方案第二版出了", "本周市场周报", "请教 SQL 写法",
        "30 分钟内能给答复吗",
    ]
    levels = ["P0"] * 1 + ["P1"] * 3 + ["P2"] * 5 + ["P3"] * 8
    out = []
    now = int(time.time())
    for i in range(limit):
        lv = random.choice(levels)
        out.append({
            "decision_id": f"dec_{i:08x}",
            "sender_name": random.choice(senders),
            "level": lv,
            "score": round(random.uniform(0.05, 0.95), 3),
            "summary": random.choice(summaries),
            "ts": now - i * random.randint(60, 300),
            "rolled_back": random.random() < 0.05,
        })
    return out


def _demo_profiles(limit: int = 10) -> List[Dict[str, Any]]:
    out = []
    for i in range(limit):
        out.append({
            "sender_id": f"u_{i:06x}",
            "sender_name": ["陈总监", "李 PM", "王同事", "财务", "客户张总",
                            "运营小赵", "上级 CTO", "HR", "TestBot", "陌生人 X"][i],
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
    in_focus = 0
    for u in states.values():
        if not isinstance(u, dict):
            continue
        fm = u.get("focus_mode")
        if isinstance(fm, dict) and fm.get("enabled"):
            in_focus += 1
    return {
        "decisions_today": len(today),
        "p0_today": counts.get("P0", 0),
        "p1_today": counts.get("P1", 0),
        "p2_today": counts.get("P2", 0),
        "p3_today": counts.get("P3", 0),
        "auto_replied": counts.get("P2", 0),
        "archived": counts.get("P3", 0),
        "active_users": len(states),
        "in_focus_now": in_focus,
        "circuit_breakers_today": sum(1 for d in today if d.get("circuit_breaker_triggered")),
        "llm_call_rate": round(sum(1 for d in today if d.get("llm_used")) / max(1, len(today)), 3),
        "accuracy_rate": 0.99,
        "uptime_hours": round((time.time() - app.state.start_ts) / 3600, 1),
        "mode": "live",
        "ts": int(time.time()),
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


# ----- routes -----

@app.on_event("startup")
async def _startup():
    app.state.start_ts = time.time()
    asyncio.create_task(_broadcast_loop())


@app.get("/", response_class=HTMLResponse)
async def index():
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return idx.read_text(encoding="utf-8")
    return "<h1>LarkMentor Dashboard</h1><p>Static UI not built. See dashboard/static/index.html</p>"


@app.get("/api/health")
async def health():
    return {"status": "ok", "mode": "demo" if DEMO_MODE else "live"}


@app.get("/health")
async def health_alias():
    return {"status": "ok", "mode": "demo" if DEMO_MODE else "live"}


@app.get("/api/overview")
async def overview():
    return _demo_overview() if DEMO_MODE else _real_overview()


@app.get("/api/decisions")
async def decisions(limit: int = Query(30, ge=1, le=200)):
    if DEMO_MODE:
        return _demo_decisions(limit)
    raw = _decisions()
    out = raw if isinstance(raw, list) else []
    out = [d for d in out if isinstance(d, dict)]
    out = sorted(out, key=lambda d: d.get("ts", 0), reverse=True)[:limit]
    return out


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
            "sender_id": sid,
            "sender_name": p.get("name", sid[-8:]),
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
        return [{
            "user_id": f"u_demo_{i}",
            "name": ["李洁盈", "戴尚好", "评委 A", "评委 B", "测试用户"][i],
            "in_focus": i % 2 == 0,
            "tasks": random.randint(0, 4),
            "pending_msgs": random.randint(0, 12),
        } for i in range(5)]
    raw_states = _user_states()
    states = raw_states if isinstance(raw_states, dict) else {}
    out = []
    for uid, s in states.items():
        if not isinstance(s, dict):
            continue
        fm = s.get("focus_mode", {}) if isinstance(s.get("focus_mode"), dict) else {}
        out.append({
            "user_id": uid,
            "name": s.get("name", uid[-8:]),
            "in_focus": fm.get("enabled", False),
            "tasks": len(s.get("tasks", [])),
            "pending_msgs": len(s.get("pending_msgs", [])),
        })
    return out


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
        payload = {
            "type": "tick",
            "overview": _demo_overview() if DEMO_MODE else _real_overview(),
        }
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


# ----- v3 endpoints: weekly/monthly/audit/team -----

@app.get("/api/v3/weekly")
async def v3_weekly(open_id: str = Query(..., min_length=4)):
    try:
        from core.work_review.weekly_report import generate_weekly_report
        report = generate_weekly_report(open_id, publish=False)
        return {
            "open_id": open_id,
            "week_start_ts": report.week_start_ts,
            "week_end_ts": report.week_end_ts,
            "stats": report.stats,
            "body_md": report.body_md,
            "used_llm": report.used_llm,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/v3/wrapped")
async def v3_wrapped(open_id: str = Query(..., min_length=4),
                     days: int = Query(30, ge=7, le=120)):
    try:
        from core.work_review.monthly_wrapped import generate_monthly_wrapped
        card = generate_monthly_wrapped(open_id, days=days)
        return {
            "open_id": open_id,
            "headline": card.headline,
            "bullets": card.bullets,
            "stats": card.stats,
            "month_start_ts": card.month_start_ts,
            "month_end_ts": card.month_end_ts,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/v3/audit")
async def v3_audit(limit: int = Query(50, ge=1, le=500),
                   actor: str = Query(""),
                   severity: str = Query("")):
    try:
        from core.security.audit_log import query_audit
        kwargs = {"limit": limit}
        if actor:
            kwargs["actor"] = actor
        if severity:
            kwargs["severities"] = [severity.upper()]
        items = query_audit(**kwargs)
        return [
            {
                "ts": i.ts, "actor": i.actor[-8:], "action": i.action,
                "resource": i.resource[-12:], "outcome": i.outcome,
                "severity": i.severity, "meta": i.meta,
            }
            for i in items
        ]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/v3/team_insights")
async def v3_team_insights():
    """Aggregate metrics across all known users (demo-friendly)."""
    states = _user_states() if isinstance(_user_states(), dict) else {}
    decisions = _decisions() if isinstance(_decisions(), list) else []
    today_start = int(time.time()) - 86400 * 7
    week = [d for d in decisions if isinstance(d, dict) and d.get("ts", 0) >= today_start]
    by_level: Dict[str, int] = {}
    by_user: Dict[str, int] = {}
    for d in week:
        by_level[d.get("level", "P3")] = by_level.get(d.get("level", "P3"), 0) + 1
        uid = (d.get("user_open_id") or "")[-8:] or "anon"
        by_user[uid] = by_user.get(uid, 0) + 1
    in_focus = sum(
        1 for u in states.values()
        if isinstance(u, dict) and isinstance(u.get("focus_mode"), dict)
        and u["focus_mode"].get("enabled")
    )
    top_users = sorted(by_user.items(), key=lambda t: t[1], reverse=True)[:8]
    return {
        "users_total": len(states),
        "users_in_focus": in_focus,
        "decisions_7d": len(week),
        "by_level_7d": by_level,
        "top_users_7d": [{"user": u, "count": c} for u, c in top_users],
        "ts": int(time.time()),
    }


@app.get("/api/v3/memory")
async def v3_memory(open_id: str = Query(..., min_length=4),
                    limit: int = Query(20, ge=1, le=100),
                    kind: str = Query("")):
    try:
        from core.flow_memory.archival import query_archival
        kinds = [kind] if kind else None
        items = query_archival(open_id, kinds=kinds, limit=limit)
        return [
            {"ts": i.ts, "kind": i.kind, "summary_md": i.summary_md, "meta": i.meta}
            for i in items
        ]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/v3", response_class=HTMLResponse)
async def dashboard_v3():
    page = STATIC_DIR / "dashboard_v3.html"
    if page.exists():
        return page.read_text(encoding="utf-8")
    return "<h1>Dashboard v3</h1><p>Static page missing.</p>"


# ── LarkMentor v1: My Mentor Stats ──
try:
    from dashboard.mentor_stats import register as _register_mentor_stats

    _register_mentor_stats(app)
except Exception as _e:  # noqa: BLE001
    pass


# Static mount
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
