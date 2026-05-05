"""Legacy dashboard endpoints (v3/v7 compat) and demo data generators."""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter(tags=["legacy"])

STATIC_DIR = Path(__file__).parent.parent / "static"


@router.get("/api/v3/weekly")
async def v3_weekly(open_id: str = Query(..., min_length=4)):
    try:
        from core.work_review.weekly_report import generate_weekly_report
        report = generate_weekly_report(open_id, publish=False)
        return {
            "open_id": open_id, "week_start_ts": report.week_start_ts,
            "week_end_ts": report.week_end_ts, "stats": report.stats,
            "body_md": report.body_md, "used_llm": report.used_llm,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/v3/wrapped")
async def v3_wrapped(open_id: str = Query(..., min_length=4), days: int = Query(30, ge=7, le=120)):
    try:
        from core.work_review.monthly_wrapped import generate_monthly_wrapped
        card = generate_monthly_wrapped(open_id, days=days)
        return {
            "open_id": open_id, "headline": card.headline,
            "bullets": card.bullets, "stats": card.stats,
            "month_start_ts": card.month_start_ts, "month_end_ts": card.month_end_ts,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/v3/audit")
async def v3_audit(limit: int = Query(50, ge=1, le=500), actor: str = Query(""), severity: str = Query("")):
    try:
        from core.security.audit_log import query_audit
        kwargs: Dict[str, Any] = {"limit": limit}
        if actor:
            kwargs["actor"] = actor
        if severity:
            kwargs["severities"] = [severity.upper()]
        items = query_audit(**kwargs)
        return [
            {"ts": i.ts, "actor": i.actor[-8:], "action": i.action,
             "resource": i.resource[-12:], "outcome": i.outcome,
             "severity": i.severity, "meta": i.meta}
            for i in items
        ]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/v3/team_insights")
async def v3_team_insights():
    from dashboard.server import _decisions, _user_states
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
        if isinstance(u, dict) and isinstance(u.get("focus_mode"), dict) and u["focus_mode"].get("enabled")
    )
    top_users = sorted(by_user.items(), key=lambda t: t[1], reverse=True)[:8]
    return {
        "users_total": len(states), "users_in_focus": in_focus,
        "decisions_7d": len(week), "by_level_7d": by_level,
        "top_users_7d": [{"user": u, "count": c} for u, c in top_users],
        "ts": int(time.time()),
    }


@router.get("/api/v3/memory")
async def v3_memory(
    open_id: str = Query(..., min_length=4), limit: int = Query(20, ge=1, le=100), kind: str = Query("")
):
    try:
        from core.flow_memory.archival import query_archival
        kinds = [kind] if kind else None
        items = query_archival(open_id, kinds=kinds, limit=limit)
        return [{"ts": i.ts, "kind": i.kind, "summary_md": i.summary_md, "meta": i.meta} for i in items]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/v3", response_class=HTMLResponse)
async def dashboard_v3():
    page = STATIC_DIR / "dashboard_v3.html"
    if page.exists():
        return page.read_text(encoding="utf-8")
    return "<h1>Dashboard v3</h1><p>Static page missing.</p>"


@router.get("/v7/pilot", response_class=HTMLResponse)
@router.get("/v7", response_class=HTMLResponse)
async def pilot_v7_dashboard():
    v7_dir = Path(__file__).parent.parent / "static_v7"
    page = v7_dir / "pilot_v7.html"
    if page.exists():
        return page.read_text(encoding="utf-8")
    return HTMLResponse(status_code=301, headers={"Location": "/v12/dashboard"})
