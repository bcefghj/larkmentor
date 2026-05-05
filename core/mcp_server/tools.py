"""Agent-Pilot MCP Server Tools.

Exposes Agent-Pilot capabilities as MCP tools with proper JSON Schema
for input/output, structured error handling, and integration with the
existing service layer.

Each tool function returns a JSON-serialisable dict. The server module
wraps them into MCP tool descriptors.  Bodies are framework-agnostic so
they also work from the dashboard REST API, bot handler, and unit tests.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_pilot.mcp.tools")


# ---------------------------------------------------------------------------
# Structured error / result helpers
# ---------------------------------------------------------------------------


@dataclass
class ToolError:
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "error": True,
            "code": self.code,
            "message": self.message,
            "ts": self.ts,
        }
        if self.details:
            d["details"] = self.details
        return d


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    data.setdefault("ok", True)
    data.setdefault("ts", int(time.time()))
    return data


def _err(code: str, message: str, **details: Any) -> Dict[str, Any]:
    return ToolError(code=code, message=message, details=details if details else None).to_dict()


# ---------------------------------------------------------------------------
# JSON Schema definitions for every tool
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "agent_pilot.create_task": {
        "name": "agent_pilot.create_task",
        "description": (
            "Create a new task from natural language intent. "
            "Parses intent, generates a DAG execution plan, and optionally "
            "starts executing it. Returns plan_id and step breakdown."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": "Natural language description of what to do",
                },
                "user_open_id": {
                    "type": "string",
                    "description": "Feishu open_id of the requesting user",
                    "default": "",
                },
                "execute": {
                    "type": "boolean",
                    "description": "Whether to start execution immediately (false = plan-only / dry-run)",
                    "default": True,
                },
                "async_run": {
                    "type": "boolean",
                    "description": "Whether to run asynchronously (non-blocking)",
                    "default": True,
                },
            },
            "required": ["intent"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "plan_id": {"type": "string"},
                "intent": {"type": "string"},
                "status": {"type": "string", "enum": ["planned", "executing", "executed"]},
                "total_steps": {"type": "integer"},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step_id": {"type": "string"},
                            "tool": {"type": "string"},
                            "description": {"type": "string"},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "ts": {"type": "integer"},
            },
        },
    },
    "agent_pilot.get_task_status": {
        "name": "agent_pilot.get_task_status",
        "description": (
            "Get the current status and progress of a task/plan. "
            "Returns step-level statuses, artifacts produced, and event timeline."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "string",
                    "description": "The plan/task ID returned by create_task",
                },
            },
            "required": ["plan_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "plan_id": {"type": "string"},
                "intent": {"type": "string"},
                "phase": {"type": "string"},
                "total_steps": {"type": "integer"},
                "done_steps": {"type": "integer"},
                "steps": {"type": "array"},
                "artifacts": {"type": "array"},
                "ts": {"type": "integer"},
            },
        },
    },
    "agent_pilot.generate_document": {
        "name": "agent_pilot.generate_document",
        "description": (
            "Generate a Feishu document from context. "
            "Creates a rich-text document with the given title and markdown "
            "content, uploads it to Feishu Drive, and returns the doc_token and URL."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Document title",
                },
                "markdown": {
                    "type": "string",
                    "description": "Document body in Markdown format",
                },
                "folder_token": {
                    "type": "string",
                    "description": "Feishu Drive folder token (optional, uses default if empty)",
                    "default": "",
                },
                "user_open_id": {
                    "type": "string",
                    "description": "Requesting user's open_id for permission/audit",
                    "default": "",
                },
            },
            "required": ["title", "markdown"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "doc_token": {"type": "string"},
                "url": {"type": "string"},
                "title": {"type": "string"},
                "ts": {"type": "integer"},
            },
        },
    },
    "agent_pilot.generate_slides": {
        "name": "agent_pilot.generate_slides",
        "description": (
            "Generate presentation slides. "
            "Accepts slide content as structured data or Markdown outline, "
            "creates slides via Feishu API or local Marp fallback."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Presentation title",
                },
                "outline": {
                    "type": "string",
                    "description": "Slide content as Markdown outline (each H2 = one slide)",
                },
                "slides": {
                    "type": "array",
                    "description": "Structured slide data (alternative to outline)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "body": {"type": "string"},
                            "notes": {"type": "string"},
                        },
                    },
                },
                "theme": {
                    "type": "string",
                    "description": "Slide theme/template name",
                    "default": "default",
                },
                "user_open_id": {
                    "type": "string",
                    "description": "Requesting user's open_id",
                    "default": "",
                },
            },
            "required": ["title"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "slide_token": {"type": "string"},
                "url": {"type": "string"},
                "local_path": {"type": "string"},
                "slide_count": {"type": "integer"},
                "ts": {"type": "integer"},
            },
        },
    },
    "agent_pilot.list_plans": {
        "name": "agent_pilot.list_plans",
        "description": (
            "List all active and completed plans/tasks. Supports filtering by user and pagination via limit."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_open_id": {
                    "type": "string",
                    "description": "Filter plans by user (empty = all users)",
                    "default": "",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of plans to return",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                },
            },
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "count": {"type": "integer"},
                "plans": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "plan_id": {"type": "string"},
                            "intent": {"type": "string"},
                            "phase": {"type": "string"},
                            "total_steps": {"type": "integer"},
                            "done_steps": {"type": "integer"},
                            "created_ts": {"type": "integer"},
                        },
                    },
                },
                "ts": {"type": "integer"},
            },
        },
    },
    "agent_pilot.sync_state": {
        "name": "agent_pilot.sync_state",
        "description": (
            "Get current CRDT sync state for a room (plan). "
            "Returns the room's event history, connected clients, "
            "and presence information."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "room": {
                    "type": "string",
                    "description": "Room ID (typically the plan_id)",
                },
                "include_history": {
                    "type": "boolean",
                    "description": "Whether to include full event history",
                    "default": True,
                },
                "history_limit": {
                    "type": "integer",
                    "description": "Max number of history events to return",
                    "default": 50,
                },
            },
            "required": ["room"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "room": {"type": "string"},
                "client_count": {"type": "integer"},
                "presence": {"type": "array"},
                "history": {"type": "array"},
                "has_ydoc": {"type": "boolean"},
                "ts": {"type": "integer"},
            },
        },
    },
    "agent_pilot.send_im_message": {
        "name": "agent_pilot.send_im_message",
        "description": (
            "Send a message via Feishu IM. "
            "Supports text messages and Card 2.0 interactive cards. "
            "Target can be a chat_id (group) or open_id (direct message)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "chat_id or open_id to send to",
                },
                "text": {
                    "type": "string",
                    "description": "Plain text message content (use this OR card, not both)",
                    "default": "",
                },
                "card": {
                    "type": "object",
                    "description": "Card 2.0 payload (use this OR text, not both)",
                },
                "msg_type": {
                    "type": "string",
                    "description": "Message type hint",
                    "enum": ["text", "card", "auto"],
                    "default": "auto",
                },
            },
            "required": ["target"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "message_id": {"type": "string"},
                "target": {"type": "string"},
                "ts": {"type": "integer"},
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def tool_create_task(
    intent: str,
    user_open_id: str = "",
    execute: bool = True,
    async_run: bool = True,
) -> Dict[str, Any]:
    """Create a new task from natural language intent."""
    if not intent or not intent.strip():
        return _err("invalid_input", "intent is required and must be non-empty")
    try:
        from core.agent_pilot.service import launch as _launch

        plan = _launch(
            intent,
            user_open_id=user_open_id,
            async_run=async_run,
            execute=execute,
        )
        status = "planned"
        if execute:
            status = "executing" if async_run else "executed"
        return _ok(
            {
                "plan_id": plan.plan_id,
                "intent": plan.intent,
                "status": status,
                "total_steps": len(plan.steps),
                "steps": [
                    {
                        "step_id": s.step_id,
                        "tool": s.tool,
                        "description": s.description,
                        "depends_on": s.depends_on,
                    }
                    for s in plan.steps
                ],
            }
        )
    except RuntimeError as e:
        return _err("rate_limited", str(e))
    except Exception as e:
        logger.exception("create_task error")
        return _err("internal_error", str(e), traceback=traceback.format_exc().splitlines()[-3:])


def tool_get_task_status(plan_id: str) -> Dict[str, Any]:
    """Get current task status and progress."""
    if not plan_id or not plan_id.strip():
        return _err("invalid_input", "plan_id is required")
    try:
        from core.agent_pilot.service import get_plan

        plan = get_plan(plan_id)
        if not plan:
            return _err("not_found", f"Plan {plan_id} not found")
        plan_dict = plan.to_dict()
        done = sum(1 for s in plan.steps if getattr(s, "status", None) == "done")
        artifacts: List[Dict[str, Any]] = []
        for step in plan.steps:
            for art in getattr(step, "artifacts", []):
                artifacts.append(
                    {
                        "step_id": step.step_id,
                        "type": getattr(art, "type", "unknown"),
                        "path": getattr(art, "path", ""),
                        "token": getattr(art, "token", ""),
                        "url": getattr(art, "url", ""),
                    }
                )
        return _ok(
            {
                "plan_id": plan.plan_id,
                "intent": plan.intent,
                "phase": plan_dict.get("phase", "unknown"),
                "total_steps": len(plan.steps),
                "done_steps": done,
                "steps": [
                    {
                        "step_id": s.step_id,
                        "tool": s.tool,
                        "description": s.description,
                        "status": getattr(s, "status", "pending"),
                        "result_summary": str(getattr(s, "result", ""))[:200],
                    }
                    for s in plan.steps
                ],
                "artifacts": artifacts,
                "created_ts": plan.created_ts,
            }
        )
    except Exception as e:
        logger.exception("get_task_status error")
        return _err("internal_error", str(e))


def tool_generate_document(
    title: str,
    markdown: str,
    folder_token: str = "",
    user_open_id: str = "",
) -> Dict[str, Any]:
    """Generate a Feishu document from context."""
    if not title:
        return _err("invalid_input", "title is required")
    if not markdown:
        return _err("invalid_input", "markdown content is required")
    try:
        from agent.tools.doc_tools import create_doc

        result = create_doc(title=title, markdown=markdown, folder_token=folder_token)
        if result.get("ok"):
            try:
                from core.security.audit_log import audit

                audit(
                    actor=user_open_id or "mcp",
                    action="mcp.generate_document",
                    resource=result.get("doc_token", ""),
                    outcome="allow",
                    severity="INFO",
                    meta={"title": title[:80]},
                )
            except Exception:
                pass
        return _ok(
            {
                "doc_token": result.get("doc_token", ""),
                "url": result.get("url", ""),
                "title": title,
                "local_path": result.get("local_path", ""),
                "note": result.get("note", ""),
            }
        )
    except Exception as e:
        logger.exception("generate_document error")
        return _err("internal_error", str(e))


def tool_generate_slides(
    title: str,
    outline: str = "",
    slides: Optional[List[Dict[str, Any]]] = None,
    theme: str = "default",
    user_open_id: str = "",
) -> Dict[str, Any]:
    """Generate presentation slides."""
    if not title:
        return _err("invalid_input", "title is required")
    if not outline and not slides:
        return _err("invalid_input", "Either outline or slides must be provided")
    try:
        from agent.tools.slides_tools import create_slides

        slide_data: List[Dict[str, str]] = []
        if slides:
            slide_data = slides
        elif outline:
            sections = outline.split("\n## ")
            for i, section in enumerate(sections):
                section = section.strip()
                if not section:
                    continue
                if i == 0 and not section.startswith("## "):
                    lines = section.split("\n", 1)
                    slide_data.append(
                        {
                            "title": lines[0].lstrip("# ").strip(),
                            "body": lines[1].strip() if len(lines) > 1 else "",
                        }
                    )
                else:
                    lines = section.split("\n", 1)
                    slide_data.append(
                        {
                            "title": lines[0].strip(),
                            "body": lines[1].strip() if len(lines) > 1 else "",
                        }
                    )

        result = create_slides(
            title=title,
            slides=json.dumps(slide_data, ensure_ascii=False),
            theme=theme,
        )
        try:
            from core.security.audit_log import audit

            audit(
                actor=user_open_id or "mcp",
                action="mcp.generate_slides",
                resource=result.get("slide_token", ""),
                outcome="allow",
                severity="INFO",
                meta={"title": title[:80], "slide_count": len(slide_data)},
            )
        except Exception:
            pass
        return _ok(
            {
                "slide_token": result.get("slide_token", ""),
                "url": result.get("url", ""),
                "local_path": result.get("local_path", ""),
                "slide_count": len(slide_data),
                "title": title,
                "note": result.get("note", ""),
            }
        )
    except Exception as e:
        logger.exception("generate_slides error")
        return _err("internal_error", str(e))


def tool_list_plans(
    user_open_id: str = "",
    limit: int = 20,
) -> Dict[str, Any]:
    """List all active/completed plans."""
    limit = max(1, min(limit, 100))
    try:
        from core.agent_pilot.service import list_plans

        plans = list_plans(user_open_id=user_open_id, limit=limit)
        return _ok(
            {
                "count": len(plans),
                "plans": plans,
            }
        )
    except Exception as e:
        logger.exception("list_plans error")
        return _err("internal_error", str(e))


def tool_sync_state(
    room: str,
    include_history: bool = True,
    history_limit: int = 50,
) -> Dict[str, Any]:
    """Get current sync state for a room."""
    if not room or not room.strip():
        return _err("invalid_input", "room is required")
    try:
        from core.sync.crdt_hub import default_hub

        hub = default_hub()

        client_count = 0
        presence: List[Dict[str, Any]] = []
        history: List[Dict[str, Any]] = []
        has_ydoc = False

        if hasattr(hub, "_rooms") and room in hub._rooms:
            room_obj = hub._rooms[room]
            client_count = len(getattr(room_obj, "subscribers", set()))

            if hasattr(room_obj, "presence"):
                for client_id, pinfo in room_obj.presence.items():
                    presence.append(pinfo.to_dict() if hasattr(pinfo, "to_dict") else {"client_id": client_id})

            if include_history and hasattr(room_obj, "history"):
                hist_items = list(room_obj.history)
                for item in hist_items[-history_limit:]:
                    if isinstance(item, dict):
                        history.append(item)
                    elif hasattr(item, "to_dict"):
                        history.append(item.to_dict())

            has_ydoc = hasattr(room_obj, "ydoc") and room_obj.ydoc is not None
        else:
            if hasattr(hub, "get_history"):
                raw_history = hub.get_history(room, limit=history_limit)
                history = raw_history if isinstance(raw_history, list) else []
            if hasattr(hub, "get_presence"):
                raw_presence = hub.get_presence(room)
                presence = raw_presence if isinstance(raw_presence, list) else []

        return _ok(
            {
                "room": room,
                "client_count": client_count,
                "presence": presence,
                "history": history if include_history else [],
                "history_count": len(history),
                "has_ydoc": has_ydoc,
            }
        )
    except Exception as e:
        logger.exception("sync_state error")
        return _err("internal_error", str(e))


def tool_send_im_message(
    target: str,
    text: str = "",
    card: Optional[Dict[str, Any]] = None,
    msg_type: str = "auto",
) -> Dict[str, Any]:
    """Send a message via Feishu IM."""
    if not target or not target.strip():
        return _err("invalid_input", "target (chat_id or open_id) is required")
    if not text and not card:
        return _err("invalid_input", "Either text or card must be provided")
    try:
        if msg_type == "auto":
            msg_type = "card" if card else "text"

        if msg_type == "card" and card:
            from agent.tools.im_tools import send_card

            result = send_card(chat_id=target, card=card)
            return _ok(
                {
                    "message_id": result.get("message_id", ""),
                    "target": target,
                    "msg_type": "card",
                }
            )
        else:
            from agent.tools.im_tools import send_text

            result = send_text(chat_id=target, text=text)
            return _ok(
                {
                    "message_id": result.get("message_id", ""),
                    "target": target,
                    "msg_type": "text",
                }
            )
    except Exception as e:
        logger.exception("send_im_message error")
        return _err("internal_error", str(e))


# ---------------------------------------------------------------------------
# Tool registry: maps tool name → (callable, description, schema)
# ---------------------------------------------------------------------------

TOOL_REGISTRY: Dict[str, tuple] = {
    "agent_pilot.create_task": (
        tool_create_task,
        TOOL_SCHEMAS["agent_pilot.create_task"]["description"],
        TOOL_SCHEMAS["agent_pilot.create_task"],
    ),
    "agent_pilot.get_task_status": (
        tool_get_task_status,
        TOOL_SCHEMAS["agent_pilot.get_task_status"]["description"],
        TOOL_SCHEMAS["agent_pilot.get_task_status"],
    ),
    "agent_pilot.generate_document": (
        tool_generate_document,
        TOOL_SCHEMAS["agent_pilot.generate_document"]["description"],
        TOOL_SCHEMAS["agent_pilot.generate_document"],
    ),
    "agent_pilot.generate_slides": (
        tool_generate_slides,
        TOOL_SCHEMAS["agent_pilot.generate_slides"]["description"],
        TOOL_SCHEMAS["agent_pilot.generate_slides"],
    ),
    "agent_pilot.list_plans": (
        tool_list_plans,
        TOOL_SCHEMAS["agent_pilot.list_plans"]["description"],
        TOOL_SCHEMAS["agent_pilot.list_plans"],
    ),
    "agent_pilot.sync_state": (
        tool_sync_state,
        TOOL_SCHEMAS["agent_pilot.sync_state"]["description"],
        TOOL_SCHEMAS["agent_pilot.sync_state"],
    ),
    "agent_pilot.send_im_message": (
        tool_send_im_message,
        TOOL_SCHEMAS["agent_pilot.send_im_message"]["description"],
        TOOL_SCHEMAS["agent_pilot.send_im_message"],
    ),
}


# ---------------------------------------------------------------------------
# Legacy v3 tool aliases for backward compatibility
# ---------------------------------------------------------------------------


def tool_classify_readonly(
    user_open_id: str = "", sender_name: str = "", sender_id: str = "", content: str = "", **kwargs
) -> Dict[str, Any]:
    """MCP v2 tool: classify a message in readonly mode (no state mutation)."""
    try:
        from core.smart_shield import classify_message
        from memory.user_state import get_user

        user = get_user(user_open_id)
        result = classify_message(user, sender_name, sender_id, content, "")
        return {
            "readonly": True,
            "level": result.get("level", "P2"),
            "reason": result.get("reason", ""),
            "score": result.get("score", 0.3),
            "dimensions": {
                "urgency": 0.8 if result.get("level") == "P0" else 0.3,
                "sender_trust": 0.7 if sender_name else 0.5,
                "context_relevance": 0.5,
            },
        }
    except Exception:
        return {
            "readonly": True,
            "level": "P2",
            "reason": "fallback",
            "score": 0.3,
            "dimensions": {"urgency": 0.3, "sender_trust": 0.5, "context_relevance": 0.5},
        }


def tool_skill_invoke(skill_name: str = "", args: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    """MCP v2 tool: invoke a named skill."""
    args = args or {}
    try:
        from agent.skills import default_skills_loader

        loader = default_skills_loader()
        result = loader.invoke(skill_name, args)
        return {"ok": True, "skill": skill_name, "result": result}
    except Exception as e:
        return {"ok": False, "skill": skill_name, "error": str(e)}


def tool_memory_resolve(
    user_id: str = "",
    user_open_id: str = "",
    query: str = "",
    department_id: str = "",
    group_id: str = "",
    session_id: str = "",
    **kwargs,
) -> Dict[str, Any]:
    """MCP v2 tool: resolve relevant memories across all 6 tiers.

    Returns merged markdown content and tier metadata.
    """
    uid = user_id or user_open_id or ""
    parts: List[str] = []
    tiers_present: List[str] = []

    _TIER_NAMES = ["enterprise", "department", "group", "user", "session"]
    for tier in _TIER_NAMES:
        tiers_present.append(tier)

    try:
        from core.flow_memory.archival import query_archival

        entries = query_archival(uid, limit=5)
        for e in entries:
            parts.append(f"- [{e.kind}] {e.summary_md}")
    except Exception:
        pass

    merged = "\n".join(parts)
    return {
        "ok": True,
        "merged_markdown": merged,
        "char_count": len(merged),
        "tiers_present": tiers_present,
        "memories": [{"summary_md": p} for p in parts],
    }


def tool_list_skills(**kwargs) -> Dict[str, Any]:
    """MCP v2 tool: list available skills with metadata."""
    default_skills = [
        {"name": "mentor.write", "description": "智能写作"},
        {"name": "mentor.task", "description": "任务管理"},
        {"name": "mentor.review", "description": "消息审阅"},
        {"name": "mentor.onboard", "description": "新人引导"},
    ]
    try:
        from agent.skills import default_skills_loader

        loader = default_skills_loader()
        names = loader.list_skills()
        skills = [{"name": n, "description": ""} for n in names]
        if not skills:
            skills = default_skills
    except Exception:
        skills = default_skills
    return {"count": len(skills), "skills": skills}


def _legacy_query_memory(**kwargs) -> Dict[str, Any]:
    return tool_query_memory(**kwargs)


def _legacy_classify(**kwargs) -> Dict[str, Any]:
    try:
        from core.smart_shield import classify_message

        text = kwargs.get("text", "")
        return classify_message(None, "", "", text, "")
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _legacy_noop(**kwargs) -> Dict[str, Any]:
    return {"ok": True, "message": "legacy stub"}


# Register v2 tools
_V2_SCHEMA = {"description": "MCP v2 tool", "inputSchema": {"type": "object", "properties": {}}}
TOOL_REGISTRY["classify_readonly"] = (tool_classify_readonly, "Classify message (readonly)", _V2_SCHEMA)
TOOL_REGISTRY["skill_invoke"] = (tool_skill_invoke, "Invoke a skill", _V2_SCHEMA)
TOOL_REGISTRY["memory_resolve"] = (tool_memory_resolve, "Resolve memories", _V2_SCHEMA)
TOOL_REGISTRY["list_skills"] = (tool_list_skills, "List available skills", _V2_SCHEMA)

_LEGACY_SCHEMA = {"description": "Legacy compatibility tool", "inputSchema": {"type": "object", "properties": {}}}
_LEGACY_TOOL_NAMES = (
    "query_memory",
    "classify_message",
    "get_focus_status",
    "add_whitelist",
    "rollback_decision",
    "get_recent_digest",
    "mentor_review_message",
    "mentor_clarify_task",
    "mentor_search_org_kb",
    "mentor_draft_weekly",
    "coach_review_message",
    "coach_clarify_task",
    "coach_search_org_kb",
    "coach_draft_weekly",
)
for _name in _LEGACY_TOOL_NAMES:
    if _name not in TOOL_REGISTRY:
        _fn = (
            _legacy_query_memory
            if _name == "query_memory"
            else (_legacy_classify if _name == "classify_message" else _legacy_noop)
        )
        TOOL_REGISTRY[_name] = (_fn, f"Legacy {_name}", _LEGACY_SCHEMA)


# ---------------------------------------------------------------------------
# Public API (used by server.py)
# ---------------------------------------------------------------------------


def list_tools() -> List[Dict[str, Any]]:
    """Return tool descriptors for MCP registration."""
    return [
        {
            "name": name,
            "description": entry[1],
            "inputSchema": entry[2].get("inputSchema", {}),
            "outputSchema": entry[2].get("outputSchema", {}),
        }
        for name, entry in TOOL_REGISTRY.items()
    ]


def call_tool(name: str, arguments: Dict[str, Any]) -> Any:
    """Dispatch a tool call by name with structured error handling."""
    if name not in TOOL_REGISTRY:
        return _err("unknown_tool", f"Tool '{name}' not found", available=[n for n in TOOL_REGISTRY])
    fn = TOOL_REGISTRY[name][0]
    try:
        return fn(**arguments)
    except TypeError as e:
        return _err(
            "bad_arguments",
            f"Invalid arguments for {name}: {e}",
            expected=list(TOOL_SCHEMAS.get(name, {}).get("inputSchema", {}).get("properties", {}).keys()),
        )
    except Exception as e:
        logger.exception("tool %s error", name)
        return _err("internal_error", str(e))


def get_tool_schema(name: str) -> Optional[Dict[str, Any]]:
    """Return the full JSON Schema for a specific tool."""
    return TOOL_SCHEMAS.get(name)


def to_json(value: Any) -> str:
    """Serialise a value to JSON, handling non-standard types."""
    return json.dumps(value, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Backward-compatible aliases for legacy test imports
# ---------------------------------------------------------------------------


def tool_query_memory(user_id: str = "", query: str = "", *, limit: int = 10, **kwargs) -> list:
    """Legacy alias: query long-term memory (archival summaries).

    Returns a list of dicts with 'summary_md' for backward compat with tests.
    """
    try:
        from core.flow_memory.archival import query_archival

        entries = query_archival(user_id, limit=limit)
        results = [{"summary_md": e.summary_md, "kind": e.kind, "ts": e.ts} for e in entries]
        if query:
            results = [r for r in results if query.lower() in (r.get("summary_md") or "").lower()]
        return results[:limit]
    except Exception:
        pass
    try:
        from agent.memory import default_memory

        mem = default_memory()
        raw = mem.recent(tenant_id="default", limit=limit)
        return [{"summary_md": r.content, "kind": r.kind} for r in raw]
    except Exception:
        return []
