"""Tool implementations exposed by the LarkMentor MCP Server.

Each function returns a JSON-serialisable dict; the server module wraps
them into MCP tool descriptors. We deliberately keep the bodies framework-
agnostic so they can also be reused by the dashboard REST API, the bot
command handler, and unit tests.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from core.flow_memory.archival import query_archival
from core.flow_memory.working import WorkingMemory
from core.security.audit_log import audit, query_audit
from core.security.permission_manager import default_manager

logger = logging.getLogger("flowguard.mcp.tools")


# --- 1. get_focus_status -----------------------------------------------------

def tool_get_focus_status(open_id: str) -> Dict[str, Any]:
    """Return the live focus state of a given user."""
    try:
        from memory.user_state import get_user
        u = get_user(open_id)
        return {
            "open_id": open_id,
            "is_focusing": bool(u and u.is_focusing()),
            "focus_start_ts": getattr(u, "focus_start_ts", 0) if u else 0,
            "focus_duration_sec": getattr(u, "focus_duration_sec", 0) if u else 0,
            "work_context": getattr(u, "work_context", "") if u else "",
            "ts": int(time.time()),
        }
    except Exception as e:
        return {"error": str(e), "open_id": open_id}


# --- 2. classify_message -----------------------------------------------------

def tool_classify_message(
    user_open_id: str,
    sender_name: str,
    sender_id: str,
    content: str,
    chat_name: str = "p2p",
    chat_type: str = "group",
) -> Dict[str, Any]:
    """Run the LarkMentor classifier without sending any reply (read-only)."""
    decision = default_manager().check(tool="shield.classify", user_open_id=user_open_id)
    if not decision.allowed:
        audit(actor=user_open_id, action="shield.classify",
              resource=sender_id, outcome="deny", severity="WARN",
              meta={"reason": decision.reason})
        return {"error": "permission_denied", "reason": decision.reason}
    try:
        from memory.user_state import get_user
        from core.smart_shield import process_message  # type: ignore
        user = get_user(user_open_id)
        if not user:
            return {"error": "user_not_found"}
        # Mark not-actually-focusing path: the caller might be just checking.
        result = process_message(
            user=user, sender_name=sender_name, sender_id=sender_id,
            message_id=f"mcp_{int(time.time()*1000)}",
            content=content, chat_name=chat_name, chat_type=chat_type,
        )
        # Strip non-serialisable items.
        return {k: v for k, v in result.items() if isinstance(v, (str, int, float, bool, list, dict))}
    except Exception as e:
        logger.exception("classify_message error")
        return {"error": str(e)}


# --- 3. get_recent_digest ----------------------------------------------------

def tool_get_recent_digest(open_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Return the most-recent N archival summaries for a user."""
    decision = default_manager().check(tool="memory.query", user_open_id=open_id)
    if not decision.allowed:
        return [{"error": "permission_denied"}]
    items = query_archival(open_id, limit=limit)
    return [
        {
            "ts": i.ts,
            "kind": i.kind,
            "summary_md": i.summary_md,
            "meta": i.meta,
        }
        for i in items
    ]


# --- 4. add_whitelist --------------------------------------------------------

def tool_add_whitelist(open_id: str, who: str) -> Dict[str, Any]:
    """Add a sender to the user's whitelist (P0 short-circuit)."""
    try:
        from memory.user_state import get_user
        u = get_user(open_id)
        if not u:
            return {"error": "user_not_found"}
        if not hasattr(u, "whitelist"):
            return {"error": "no_whitelist_field"}
        if who not in u.whitelist:
            u.whitelist.append(who)
            try:
                u.save()  # type: ignore[attr-defined]
            except Exception:
                pass
        audit(actor=open_id, action="memory.write_archival",
              resource=who, outcome="allow", severity="INFO",
              meta={"kind": "whitelist_add"})
        return {"ok": True, "whitelist_size": len(u.whitelist)}
    except Exception as e:
        return {"error": str(e)}


# --- 5. rollback_decision ----------------------------------------------------

def tool_rollback_decision(open_id: str, decision_id: str) -> Dict[str, Any]:
    """Mark a decision as rolled back; user disagreed with the AI."""
    try:
        from core.advanced_features import rollback_decision  # type: ignore
        ok = rollback_decision(decision_id)
        audit(actor=open_id, action="audit.list",
              resource=decision_id, outcome="allow" if ok else "deny",
              severity="INFO", meta={"kind": "rollback"})
        return {"ok": bool(ok), "decision_id": decision_id}
    except Exception as e:
        return {"error": str(e), "decision_id": decision_id}


# --- 6. query_memory ---------------------------------------------------------

def tool_query_memory(open_id: str, query: str, kinds: Optional[List[str]] = None,
                      limit: int = 5) -> List[Dict[str, Any]]:
    """Tiny lexical search over the user's archival summaries.

    For v3 we ship a deterministic substring matcher; an embedding-based
    retriever is on the v4 roadmap. Keeps the MCP contract stable either
    way.
    """
    decision = default_manager().check(tool="memory.query", user_open_id=open_id)
    if not decision.allowed:
        return [{"error": "permission_denied"}]
    items = query_archival(open_id, kinds=kinds, limit=200)
    q = (query or "").lower().strip()
    if not q:
        return [{"ts": i.ts, "kind": i.kind, "summary_md": i.summary_md} for i in items[:limit]]
    scored: List[tuple[int, Dict[str, Any]]] = []
    for i in items:
        body = (i.summary_md or "").lower()
        score = body.count(q)
        if score > 0:
            scored.append((score, {"ts": i.ts, "kind": i.kind, "summary_md": i.summary_md}))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [d for _, d in scored[:limit]]


# --- v4 Mentor tools ----------------------------------------------------------

def tool_mentor_review_message(
    open_id: str, message: str, recipient: str = "同事/上级",
) -> Dict[str, Any]:
    """Run the writing mentor (NVC + 3 versions + citations)."""
    decision = default_manager().check(tool="mentor.write", user_open_id=open_id)
    if not decision.allowed:
        return {"error": "permission_denied", "reason": decision.reason}
    try:
        from core.mentor.mentor_write import review

        result = review(open_id, message, recipient=recipient)
        audit(actor=open_id, action="mentor.write",
              resource="review", outcome="allow", severity="INFO",
              meta={"risk": result.risk_level, "fallback": str(result.fallback)})
        return result.to_dict()
    except Exception as e:
        logger.exception("coach_review error")
        return {"error": str(e)}


def tool_mentor_clarify_task(
    open_id: str, task_description: str, assigner: str = "上级",
) -> Dict[str, Any]:
    """Run the task mentor (ambiguity + clarification questions)."""
    decision = default_manager().check(tool="mentor.task", user_open_id=open_id)
    if not decision.allowed:
        return {"error": "permission_denied", "reason": decision.reason}
    try:
        from core.mentor.mentor_task import clarify

        result = clarify(open_id, task_description, assigner=assigner)
        audit(actor=open_id, action="mentor.task",
              resource="clarify", outcome="allow", severity="INFO",
              meta={"ambiguity": str(result.ambiguity), "fallback": str(result.fallback)})
        return result.to_dict()
    except Exception as e:
        logger.exception("coach_clarify error")
        return {"error": str(e)}


def tool_mentor_draft_weekly(open_id: str, week_offset: int = 0) -> Dict[str, Any]:
    """Run the weekly report mentor (STAR + citations)."""
    decision = default_manager().check(tool="mentor.review", user_open_id=open_id)
    if not decision.allowed:
        return {"error": "permission_denied", "reason": decision.reason}
    try:
        from core.mentor.mentor_review import draft

        result = draft(open_id, week_offset=week_offset)
        audit(actor=open_id, action="mentor.review",
              resource="draft", outcome="allow", severity="INFO",
              meta={"used_llm": str(result.used_llm), "used_star": str(result.used_star)})
        return result.to_dict()
    except Exception as e:
        logger.exception("coach_weekly error")
        return {"error": str(e)}


def tool_mentor_search_org_kb(
    open_id: str, query: str, top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Search the user's organisation knowledge base (RAG)."""
    decision = default_manager().check(tool="mentor.kb_search", user_open_id=open_id)
    if not decision.allowed:
        return [{"error": "permission_denied", "reason": decision.reason}]
    try:
        from core.mentor.knowledge_base import search, to_dict

        hits = search(open_id, query, top_k=top_k)
        return [to_dict(h) for h in hits]
    except Exception as e:
        logger.exception("coach_kb_search error")
        return [{"error": str(e)}]


# Tool registry used by the server entry point.
TOOL_REGISTRY = {
    "get_focus_status": (
        tool_get_focus_status,
        "Return the live focus state of a user. Args: open_id (str).",
    ),
    "classify_message": (
        tool_classify_message,
        "Classify a message via the LarkMentor 6-dim engine. Args: user_open_id, sender_name, sender_id, content, chat_name?, chat_type?.",
    ),
    "get_recent_digest": (
        tool_get_recent_digest,
        "Recent archival summaries for a user. Args: open_id, limit?.",
    ),
    "add_whitelist": (
        tool_add_whitelist,
        "Add a sender to the user's P0 whitelist. Args: open_id, who.",
    ),
    "rollback_decision": (
        tool_rollback_decision,
        "Mark an AI decision as rolled back. Args: open_id, decision_id.",
    ),
    "query_memory": (
        tool_query_memory,
        "Lexical search over the user's memory. Args: open_id, query, kinds?, limit?.",
    ),
    # ── v4 Mentor tools ──
    "mentor_review_message": (
        tool_mentor_review_message,
        "v4: Writing mentor. Returns NVC diagnosis + 3 rewritten versions + citations. "
        "Args: open_id, message, recipient?.",
    ),
    "mentor_clarify_task": (
        tool_mentor_clarify_task,
        "v4: Task mentor. Scores ambiguity 0-1, lists missing dims (scope/deadline/...), "
        "and either suggests 2 questions or returns understanding+plan+risks. "
        "Args: open_id, task_description, assigner?.",
    ),
    "mentor_draft_weekly": (
        tool_mentor_draft_weekly,
        "v4: Weekly report mentor. Generates STAR-formatted draft with archival citations. "
        "Args: open_id, week_offset?.",
    ),
    "mentor_search_org_kb": (
        tool_mentor_search_org_kb,
        "v4: Search the user's per-user organisation knowledge base (RAG, embedding+BM25 fallback). "
        "Args: open_id, query, top_k?.",
    ),
    # ── v4 backwards-compat aliases (old coach_* names still callable) ──
    "coach_review_message": (
        tool_mentor_review_message,
        "alias of mentor_review_message (kept for v4 backwards compat)",
    ),
    "coach_clarify_task": (
        tool_mentor_clarify_task,
        "alias of mentor_clarify_task (kept for v4 backwards compat)",
    ),
    "coach_draft_weekly": (
        tool_mentor_draft_weekly,
        "alias of mentor_draft_weekly (kept for v4 backwards compat)",
    ),
    "coach_search_org_kb": (
        tool_mentor_search_org_kb,
        "alias of mentor_search_org_kb (kept for v4 backwards compat)",
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# v2 LarkMentor: Claude Code 7 支柱外露 MCP 工具
# (step10) — classify_readonly + skill_invoke + memory_resolve
# These tools let any external Agent (Cursor / Claude Code / OpenClaw) talk
# to LarkMentor as a service without going through the Feishu Bot path.
# ─────────────────────────────────────────────────────────────────────────────


def tool_classify_readonly(
    user_open_id: str,
    sender_name: str,
    sender_id: str,
    content: str,
    chat_type: str = "p2p",
    member_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Pure read-only 6-dim classification.

    Unlike ``classify_message`` this does NOT call ``process_message`` → no
    pending log mutation, no UserState touch, no audit "WARN" if the user
    isn't focusing. Use it for scoring messages externally (e.g. a Cursor
    plugin asks "should I ping the user now?").

    Returns: ``{"level", "score", "dimensions", "short_circuit", "reason"}``.
    """
    decision = default_manager().check(tool="shield.classify", user_open_id=user_open_id)
    if not decision.allowed:
        return {"error": "permission_denied", "reason": decision.reason}
    try:
        from memory.user_state import get_user
        from core.classification_engine import classify
        from core.sender_profile import SenderProfile

        user = get_user(user_open_id)
        if user is None:
            return {"error": "user_not_found"}
        profile = SenderProfile(
            sender_id=sender_id, name=sender_name,
            identity_tag="unknown",
        )
        result = classify(
            user, profile, content, chat_type=chat_type,
            member_count=member_count,
        )
        return {
            "level": result.level,
            "score": result.score,
            "dimensions": result.dimensions,
            "short_circuit": result.short_circuit or "",
            "reason": result.reason,
            "readonly": True,
        }
    except Exception as e:
        logger.exception("classify_readonly error")
        return {"error": str(e)}


def tool_skill_invoke(
    skill_name: str,
    args: Optional[Dict[str, Any]] = None,
    user_open_id: str = "",
) -> Dict[str, Any]:
    """Generic invoke entry point that routes to default_registry.

    External Agents (Cursor / Claude Code / OpenClaw) can use this single
    tool name to invoke any LarkMentor skill without learning each
    mentor.* tool name individually.
    """
    if not skill_name:
        return {"error": "missing_skill_name"}
    args = args or {}
    try:
        from core.runtime import default_registry
        from core.mentor.skills_init import register_all
        register_all()
        return default_registry().invoke(
            skill_name, args, user_open_id=user_open_id,
        )
    except Exception as e:
        logger.exception("skill_invoke error")
        return {"ok": False, "error": str(e)}


def tool_memory_resolve(
    user_open_id: str,
    enterprise_id: str = "default",
    workspace_id: str = "default",
    department_id: Optional[str] = None,
    group_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve the merged 6-tier ``flow_memory.md`` for a given context.

    Lower tiers override higher tiers (Enterprise → Session). Use this from
    external Agents to get the same "organisation default knowledge" that
    LarkMentor injects into its own LLM prompts.
    """
    decision = default_manager().check(tool="memory.query", user_open_id=user_open_id)
    if not decision.allowed:
        return {"error": "permission_denied", "reason": decision.reason}
    try:
        from core.flow_memory.flow_memory_md import resolve_memory_md
        text = resolve_memory_md(
            enterprise_id=enterprise_id,
            workspace_id=workspace_id,
            department_id=department_id,
            group_id=group_id,
            user_open_id=user_open_id,
            session_id=session_id,
        )
        return {
            "merged_markdown": text,
            "char_count": len(text),
            "tiers_present": [t for t in [
                "enterprise", "workspace",
                "department" if department_id else None,
                "group" if group_id else None,
                "user" if user_open_id else None,
                "session" if session_id else None,
            ] if t],
        }
    except Exception as e:
        logger.exception("memory_resolve error")
        return {"error": str(e)}


def tool_list_skills() -> Dict[str, Any]:
    """List all registered Skills (manifest summary)."""
    try:
        from core.runtime import default_loader
        from core.mentor.skills_init import register_all
        register_all()
        skills = default_loader().list_skills()
        return {
            "count": len(skills),
            "skills": [
                {
                    "name": s.name,
                    "version": s.version,
                    "description": s.description,
                    "triggers": s.triggers,
                    "tools": s.tools,
                    "permission": s.permission,
                }
                for s in skills
            ],
        }
    except Exception as e:
        return {"error": str(e)}


# Register the new v2 tools in the legacy TOOL_REGISTRY dict
TOOL_REGISTRY.update({
    "classify_readonly": (
        tool_classify_readonly,
        "v2 LarkMentor: Pure read-only 6-dim classification (no UserState mutation, no pending log). "
        "Args: user_open_id, sender_name, sender_id, content, chat_type?, member_count?.",
    ),
    "skill_invoke": (
        tool_skill_invoke,
        "v2 LarkMentor: Invoke any registered Skill via the runtime ToolRegistry. "
        "Args: skill_name, args (dict), user_open_id?.",
    ),
    "memory_resolve": (
        tool_memory_resolve,
        "v2 LarkMentor: Resolve and merge the 6-tier flow_memory.md hierarchy "
        "(Enterprise/Workspace/Department/Group/User/Session). "
        "Args: user_open_id, enterprise_id?, workspace_id?, department_id?, group_id?, session_id?.",
    ),
    "list_skills": (
        tool_list_skills,
        "v2 LarkMentor: List all registered Skill manifests.",
    ),
})


def list_tools() -> List[Dict[str, str]]:
    return [{"name": k, "doc": v[1]} for k, v in TOOL_REGISTRY.items()]


def call_tool(name: str, arguments: Dict[str, Any]) -> Any:
    if name not in TOOL_REGISTRY:
        return {"error": f"unknown_tool:{name}"}
    fn, _ = TOOL_REGISTRY[name]
    try:
        return fn(**arguments)
    except TypeError as e:
        return {"error": f"bad_arguments:{e}"}
    except Exception as e:
        logger.exception("tool error")
        return {"error": str(e)}


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
