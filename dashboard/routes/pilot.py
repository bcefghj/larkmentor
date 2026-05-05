"""Agent-Pilot core API endpoints: plan management, launch, trace, cost, voice."""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/pilot", tags=["pilot"])


@router.get("/plans")
async def pilot_plans(limit: int = Query(20, ge=1, le=100), open_id: str = Query("")):
    try:
        from core.agent_pilot.service import list_plans
        return list_plans(user_open_id=open_id, limit=limit)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/plan/{plan_id}")
async def pilot_plan_detail(plan_id: str, sig: str = Query("")):
    try:
        secret = os.getenv("AGENT_PILOT_SHARE_SECRET", "")
        if secret:
            from core.agent_pilot.share_sig import verify as _verify
            if not _verify(plan_id, sig, secret=secret):
                return JSONResponse({"error": "invalid_or_expired_signature"}, status_code=403)
        from core.agent_pilot.service import get_plan
        plan = get_plan(plan_id)
        if not plan:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return plan.to_dict()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/sign/{plan_id}")
async def pilot_sign(plan_id: str, ttl: int = Query(7 * 86400, ge=60, le=30 * 86400)):
    try:
        from core.agent_pilot.share_sig import sign_url
        base = os.getenv("AGENT_PILOT_DASHBOARD_URL", "")
        return sign_url(plan_id, base_path=f"{base}/pilot/{plan_id}", ttl_sec=ttl)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/context")
async def pilot_context():
    try:
        from core.agent_pilot.harness import default_orchestrator
        orch = default_orchestrator()
        return {
            "tools": orch.tools.names(),
            "permission_mode": orch.permissions.mode.value,
            "skills": [s.name for s in orch.skills.list()],
            "hook_history": orch.hooks.history()[-20:],
            "recent_events": orch.events()[-30:],
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/skills")
async def pilot_skills():
    try:
        from core.agent_pilot.harness import default_skills
        return [
            {
                "name": s.name, "description": s.description,
                "source": s.source, "version": s.version,
                "path": s.path, "when_to_use": s.when_to_use,
            }
            for s in default_skills().list()
        ]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/mcp/servers")
async def pilot_mcp_servers():
    try:
        from core.agent_pilot.harness import default_mcp_manager
        mgr = default_mcp_manager()
        return {
            "aliases": mgr.list_aliases(),
            "tools": [
                {"alias": a, "tool": t.get("name"), "desc": (t.get("description") or "")[:120]}
                for a, t in mgr.list_tools()
            ],
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/bitable")
async def pilot_bitable_hook(body: Dict[str, Any]):
    try:
        from core.agent_pilot.service import launch
        from core.feishu_advanced.bitable_agent import build_intent_from_fields, writeback_ai_result

        data = body or {}
        intent = build_intent_from_fields(data.get("fields") or {}, data.get("intent_template", ""))
        if not intent:
            return JSONResponse({"error": "empty intent"}, status_code=400)
        plan = launch(
            intent,
            user_open_id=data.get("user_open_id", ""),
            meta={"bitable_hook": True, "app_token": data.get("app_token", ""),
                   "table_id": data.get("table_id", ""), "record_id": data.get("record_id", "")},
            async_run=True,
        )
        if data.get("app_token") and data.get("table_id") and data.get("record_id"):
            writeback_ai_result(
                app_token=data["app_token"], table_id=data["table_id"],
                record_id=data["record_id"],
                ai_field_name=data.get("ai_field_name", "AI 结果"),
                verdict="处理中", share_url=f"/pilot/{plan.plan_id}",
            )
        return {"plan_id": plan.plan_id, "intent": intent, "steps": len(plan.steps)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/scenarios")
async def pilot_scenarios():
    try:
        from core.agent_pilot.scenarios import ScenarioRegistry
        return [
            {"key": s.key, "name": s.name, "description": s.description, "entry_tools": s.entry_tools}
            for s in ScenarioRegistry.all()
        ]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/launch")
async def pilot_launch(body: Dict[str, Any]):
    try:
        from core.agent_pilot.service import launch
        intent = (body or {}).get("intent", "").strip()
        if not intent:
            return JSONResponse({"error": "intent required"}, status_code=400)
        plan = launch(intent, user_open_id=(body or {}).get("open_id", ""), async_run=True)
        return {"plan_id": plan.plan_id, "total_steps": len(plan.steps), "intent": plan.intent}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/trace/{plan_id}")
async def pilot_trace(plan_id: str):
    try:
        from core.agent_pilot.service import get_plan
        plan = get_plan(plan_id)
        if not plan:
            return JSONResponse({"error": "not_found"}, status_code=404)
        steps_trace = []
        for s in plan.steps:
            steps_trace.append({
                "step_id": s.step_id, "tool": s.tool, "status": s.status,
                "description": s.description,
                "started_ts": getattr(s, "started_ts", 0),
                "finished_ts": getattr(s, "finished_ts", 0),
                "duration_ms": (
                    (getattr(s, "finished_ts", 0) - getattr(s, "started_ts", 0)) * 1000
                    if getattr(s, "finished_ts", 0) and getattr(s, "started_ts", 0) else 0
                ),
                "error": s.error or "",
                "result_keys": list((s.result or {}).keys()) if s.result else [],
                "depends_on": s.depends_on or [],
            })
        return {
            "plan_id": plan_id, "intent": plan.intent,
            "total_steps": len(plan.steps), "steps": steps_trace, "meta": plan.meta or {},
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/cost")
async def pilot_cost_summary():
    try:
        from core.agent_pilot.harness.orchestrator_v2 import default_orchestrator
        orch = default_orchestrator()
        events = orch.events()
        plan_done_events = [e for e in events if e.get("kind") == "plan_done"]
        total_tokens = sum(e.get("payload", {}).get("total_tokens", 0) for e in plan_done_events)
        total_cost = sum(e.get("payload", {}).get("cost_usd", 0.0) for e in plan_done_events)
        return {
            "plans_completed": len(plan_done_events),
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "recent_plans": [
                {"plan_id": e.get("plan_id", ""), "verdict": e.get("payload", {}).get("verdict", ""),
                 "tokens": e.get("payload", {}).get("total_tokens", 0),
                 "elapsed_sec": e.get("payload", {}).get("elapsed_sec", 0)}
                for e in plan_done_events[-10:]
            ],
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/voice/transcribe")
async def pilot_voice_transcribe(
    audio: UploadFile = File(None),
    open_id: str = Form(""),
    minute_token: str = Form(""),
    url: str = Form(""),
):
    try:
        import tempfile
        from core.agent_pilot.planner import PlanStep
        from core.agent_pilot.tools.voice_tool import voice_transcribe

        args: Dict[str, Any] = {"open_id": open_id}
        if minute_token:
            args["minute_token"] = minute_token
        if url:
            args["url"] = url
        if audio is not None:
            suffix = os.path.splitext(audio.filename or "audio.m4a")[1] or ".m4a"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(await audio.read())
            tmp.close()
            args["file_path"] = tmp.name

        step = PlanStep(step_id="http", tool="voice.transcribe", description="http")
        return voice_transcribe(step, {"resolved_args": args, "plan_id": "", "step_results": {}})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/clarify")
async def pilot_clarify(body: Dict[str, Any]):
    try:
        from core.agent_pilot.advanced import diagnose_intent
        intent = (body or {}).get("intent", "").strip()
        if not intent:
            return JSONResponse({"error": "intent required"}, status_code=400)
        d = diagnose_intent(intent)
        return {
            "should_clarify": d.should_clarify, "ambiguity": d.ambiguity,
            "questions": d.questions, "missing_dimensions": d.missing_dimensions,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/summarise")
async def pilot_summarise(body: Dict[str, Any]):
    try:
        from core.agent_pilot.advanced import summarise_messages
        msgs = (body or {}).get("messages") or []
        return {"summary": summarise_messages(msgs)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/recommend/{plan_id}")
async def pilot_recommend(plan_id: str):
    try:
        from core.agent_pilot.advanced import recommend_next_steps
        from core.agent_pilot.service import get_plan
        plan = get_plan(plan_id)
        if not plan:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return {"plan_id": plan_id, "next_steps": recommend_next_steps(plan.to_dict())}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
