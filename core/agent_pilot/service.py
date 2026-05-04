"""High-level facade that the bot handler / dashboard / MCP server call.

Unified orchestration entry point. The ``ConversationOrchestrator`` (harness)
is the single execution engine. The legacy ``PilotOrchestrator`` is retained
only as a backwards-compatible adapter for tests that construct it directly.

Responsibilities:
    - Maintain a process-wide singleton orchestrator with CRDT hub attached
    - Provide ``launch()`` / ``get_plan()`` / ``list_plans()`` for callers
    - Persist plan state under ``data/pilot_plans/``
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from .planner import Plan, plan_from_intent

logger = logging.getLogger("pilot.service")

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "pilot_plans",
)


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


_singleton = None
_singleton_lock = threading.Lock()
_plan_cache: Dict[str, Plan] = {}


def get_orchestrator():
    """Returns the unified ConversationOrchestrator singleton.

    The harness ConversationOrchestrator is the single execution path.
    It integrates: tool registry, hooks, permissions, context management,
    memory, skills, and streaming execution with verify/reflect/replan loop.
    """
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            from .harness import ConversationOrchestrator
            orch = ConversationOrchestrator()
            try:
                from core.sync.crdt_hub import attach_orchestrator
                attach_orchestrator(orch)
            except Exception as e:
                logger.debug("attach_orchestrator skipped: %s", e)
            _singleton = orch
        return _singleton


def launch(intent: str, *, user_open_id: str = "", meta: Optional[Dict[str, Any]] = None,
           async_run: bool = True, execute: bool = True) -> Plan:
    """Launch a Plan.

    :param execute: when False the plan is generated + persisted but the
        orchestrator is not invoked. This implements Plan Mode (/plan)
        where the agent only shows the intended steps for user approval.
    """
    # P5.3: rate limit the main Pilot entrypoint.
    try:
        from core.security.rate_limiter import acquire as _acquire
        dec = _acquire(user_open_id=user_open_id or "anonymous", tool="pilot.launch")
        if not dec.allowed:
            raise RuntimeError(
                f"Pilot 启动被限流：{dec.reason}（冷却 {int(dec.reset_in_sec)}s）"
            )
    except RuntimeError:
        raise
    except Exception as _e_rl:
        logger.debug("rate limiter skipped: %s", _e_rl)
    try:
        from core.observability import incr, audit
        incr("plan_started", source=(meta or {}).get("source", "unknown"))
        audit("plan.launch", user=user_open_id, intent=intent[:120],
              source=(meta or {}).get("source", ""))
    except Exception:
        pass

    plan = plan_from_intent(intent, user_open_id=user_open_id, meta=meta)
    _plan_cache[plan.plan_id] = plan
    _persist(plan, phase="planned")

    if not execute:
        return plan

    if async_run:
        t = threading.Thread(target=_run_and_persist, args=(plan,), daemon=True)
        t.start()
    else:
        _run_and_persist(plan)
    return plan


def _run_and_persist(plan: Plan) -> None:
    try:
        orch = get_orchestrator()
        ctx = {
            "plan_id": plan.plan_id,
            "user_open_id": plan.user_open_id,
        }
        ctx.update(plan.meta or {})
        orch.run(plan, context=ctx)
    except Exception as e:
        logger.exception("pilot run failed plan=%s: %s", plan.plan_id, e)
        try:
            from core.resilience import notify_user_error
            notify_user_error(
                plan.user_open_id,
                e,
                context=f"执行计划 {plan.plan_id[:8]}... 时出错",
            )
        except Exception:
            pass
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
