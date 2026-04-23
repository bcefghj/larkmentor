"""High-level facade that the bot handler / dashboard / MCP server call.

Keeps a process-wide singleton ``PilotOrchestrator`` with:
    - the default tool registry wired in
    - the CRDT hub attached as broadcaster
    - per-plan persistence under ``data/pilot_plans/``
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from .orchestrator import PilotOrchestrator
from .planner import Plan, plan_from_intent
from .tools import build_default_registry

logger = logging.getLogger("pilot.service")

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "pilot_plans",
)


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


_singleton: Optional[PilotOrchestrator] = None
_singleton_lock = threading.Lock()
_plan_cache: Dict[str, Plan] = {}


def get_orchestrator() -> PilotOrchestrator:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            registry = build_default_registry()
            orch = PilotOrchestrator(tool_registry=registry)
            try:
                from core.sync.crdt_hub import attach_orchestrator
                attach_orchestrator(orch)
            except Exception as e:
                logger.debug("attach_orchestrator skipped: %s", e)
            _singleton = orch
        return _singleton


def launch(intent: str, *, user_open_id: str = "", meta: Optional[Dict[str, Any]] = None,
           async_run: bool = True) -> Plan:
    plan = plan_from_intent(intent, user_open_id=user_open_id, meta=meta)
    _plan_cache[plan.plan_id] = plan
    _persist(plan, phase="planned")

    if async_run:
        t = threading.Thread(target=_run_and_persist, args=(plan,), daemon=True)
        t.start()
    else:
        _run_and_persist(plan)
    return plan


def _run_and_persist(plan: Plan) -> None:
    try:
        orch = get_orchestrator()
        orch.run(plan, context={"plan_id": plan.plan_id, "user_open_id": plan.user_open_id})
    except Exception as e:
        logger.exception("pilot run failed: %s", e)
    finally:
        _persist(plan, phase="finished")


def _persist(plan: Plan, *, phase: str) -> None:
    _ensure_dir()
    path = os.path.join(DATA_DIR, f"{plan.plan_id}.json")
    try:
        payload = plan.to_dict()
        payload["persisted_ts"] = int(time.time())
        payload["phase"] = phase
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug("plan persist skipped: %s", e)


def get_plan(plan_id: str) -> Optional[Plan]:
    if plan_id in _plan_cache:
        return _plan_cache[plan_id]
    path = os.path.join(DATA_DIR, f"{plan_id}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        from .planner import Plan, PlanStep
        steps = [PlanStep(**s) for s in payload.get("steps", [])]
        p = Plan(
            plan_id=payload.get("plan_id", plan_id),
            user_open_id=payload.get("user_open_id", ""),
            intent=payload.get("intent", ""),
            steps=steps,
            created_ts=payload.get("created_ts", 0),
            meta=payload.get("meta") or {},
        )
        _plan_cache[plan_id] = p
        return p
    except Exception as e:
        logger.debug("get_plan read failed: %s", e)
        return None


def list_plans(user_open_id: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    _ensure_dir()
    out: List[Dict[str, Any]] = []
    for name in sorted(os.listdir(DATA_DIR), reverse=True):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(DATA_DIR, name), "r", encoding="utf-8") as f:
                payload = json.load(f)
            if user_open_id and payload.get("user_open_id") != user_open_id:
                continue
            out.append({
                "plan_id": payload.get("plan_id"),
                "intent": payload.get("intent", "")[:80],
                "created_ts": payload.get("created_ts", 0),
                "phase": payload.get("phase", "unknown"),
                "total_steps": len(payload.get("steps", [])),
                "done_steps": sum(1 for s in payload.get("steps", []) if s.get("status") == "done"),
            })
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out
