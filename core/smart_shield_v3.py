"""Smart Shield v3 wrapper.

Wraps the proven v1 ``smart_shield.process_message`` pipeline with the new
v3 security and memory layers without rewriting the core scoring path:

* run ``TranscriptClassifier`` first → block / redact obvious prompt
  injection attempts before they hit the LLM tie-breaker
* run ``scrub_pii`` so the LLM tie-breaker payload never sees PII
* fire the ``HookSystem`` lifecycle events for org overrides
* append every event to the user's ``WorkingMemory`` so weekly / monthly
  reports and the MCP recall tool have data to chew on

The v1 pipeline is kept untouched – switch the call site in
``bot/event_handler.py`` to this wrapper to pick up the v3 behaviour.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from core.flow_memory.working import WorkingEvent, WorkingMemory
from core.security.audit_log import audit
from core.security.hook_system import HookEvent, HookVeto, default_hooks
from core.security.permission_manager import default_manager
from core.security.pii_scrubber import scrub_pii
from core.security.transcript_classifier import (
    Action, classify_transcript, redact,
)

logger = logging.getLogger("flowguard.shield.v3")


def _record_working_memory(
    user_open_id: str, *, sender_name: str, sender_id: str,
    content: str, level: str, score: float, action: str,
) -> None:
    try:
        wm = WorkingMemory.load(user_open_id)
        wm.append(WorkingEvent(
            ts=int(time.time()), kind="message",
            payload={
                "sender_name": sender_name,
                "sender_id": sender_id,
                "content": content[:200],
                "level": level,
            },
        ))
        wm.append(WorkingEvent(
            ts=int(time.time()), kind="decision",
            payload={"action": action, "score": round(score, 3), "level": level},
        ))
        wm.save()
    except Exception as e:
        logger.debug("working memory append failed: %s", e)


def process_message_v3(
    user,
    *,
    sender_name: str, sender_id: str, message_id: str,
    content: str, chat_name: str, chat_type: str = "group",
    member_count: Optional[int] = None,
) -> Dict[str, Any]:
    """v3 entry point. Returns the same shape as v1 ``process_message``."""

    hooks = default_hooks()
    payload: Dict[str, Any] = {
        "user_open_id": user.open_id,
        "sender_name": sender_name,
        "sender_id": sender_id,
        "message_id": message_id,
        "content": content,
        "chat_name": chat_name,
        "chat_type": chat_type,
        "member_count": member_count,
    }

    # 1. Pre-classify hooks (declarative deny / force_level / etc).
    try:
        payload = hooks.fire(HookEvent.PRE_CLASSIFY, payload)
        if payload.get("_vetoed"):
            audit(actor=user.open_id, action="shield.classify",
                  resource=sender_id, outcome="deny", severity="WARN",
                  meta={"reason": payload.get("_veto_reason", "hook_veto")})
            return {
                "level": "P3", "action": "archive", "auto_reply_text": "",
                "reason": payload.get("_veto_reason", "hook_veto"),
                "score": 0.0, "dimensions": {}, "explanation": "hook veto",
                "used_llm": False, "elapsed_ms": 0,
                "circuit_breaker_triggered": False,
                "decision_id": f"veto_{message_id[-8:]}",
            }
    except Exception as e:
        logger.debug("PRE_CLASSIFY hook error: %s", e)

    # 2. Transcript classifier – defends the LLM tie-breaker against prompt
    #    injection coming from the message body.
    verdict = classify_transcript(content)
    sanitized = content
    if verdict.action is Action.BLOCK:
        audit(actor=user.open_id, action="shield.classify",
              resource=sender_id, outcome="deny", severity="HIGH",
              meta={"reason": "prompt_injection_block",
                    "tags": ",".join(verdict.tags)})
        decision = {
            "level": "P3", "action": "archive", "auto_reply_text": "",
            "reason": f"prompt_injection_block: {verdict.reason}",
            "score": 0.0, "dimensions": {}, "explanation": "blocked by transcript classifier",
            "used_llm": verdict.used_llm, "elapsed_ms": 0,
            "circuit_breaker_triggered": False,
            "decision_id": f"block_{message_id[-8:]}",
        }
        _record_working_memory(user.open_id, sender_name=sender_name, sender_id=sender_id,
                               content="[BLOCKED]", level="P3", score=0.0, action="block")
        return decision
    if verdict.action is Action.REDACT:
        sanitized = redact(content)
        audit(actor=user.open_id, action="shield.classify",
              resource=sender_id, outcome="allow", severity="WARN",
              meta={"reason": "prompt_injection_redact",
                    "tags": ",".join(verdict.tags)})

    # 3. PII scrubbing – sanitise before any LLM call.
    pii = scrub_pii(sanitized)
    if pii.counts:
        audit(actor=user.open_id, action="shield.classify",
              resource=sender_id, outcome="allow", severity="INFO",
              meta={"reason": "pii_scrubbed",
                    "kinds": ",".join(pii.counts.keys()),
                    "count": str(sum(pii.counts.values()))})
    safe_content = pii.redacted_text

    # 4. Permission gate – record-only, since classification itself is read.
    decision = default_manager().check(tool="shield.classify", user_open_id=user.open_id)
    if not decision.allowed:
        return {"level": "P3", "action": "archive", "auto_reply_text": "",
                "reason": f"permission_denied: {decision.reason}",
                "score": 0.0, "dimensions": {}, "explanation": "permission denied",
                "used_llm": False, "elapsed_ms": 0,
                "circuit_breaker_triggered": False,
                "decision_id": f"perm_{message_id[-8:]}"}

    # 5. Run the proven v1 pipeline with the sanitised payload.
    from core.smart_shield import process_message  # local import: cheap, avoids cycles
    result = process_message(
        user=user, sender_name=sender_name, sender_id=sender_id,
        message_id=message_id, content=safe_content,
        chat_name=chat_name, chat_type=chat_type, member_count=member_count,
    )

    # 6. Force-level override from hook (e.g. "boss DM always P0").
    forced = payload.get("forced_level")
    if forced and forced != result.get("level"):
        audit(actor=user.open_id, action="shield.classify",
              resource=sender_id, outcome="allow", severity="INFO",
              meta={"reason": "hook_force_level",
                    "from": str(result.get("level")), "to": forced})
        result["level"] = forced
        result["reason"] = (result.get("reason") or "") + f" | forced={forced}"

    # 7. Memory + post-classify hook + reply guard.
    _record_working_memory(
        user.open_id, sender_name=sender_name, sender_id=sender_id,
        content=safe_content, level=result["level"],
        score=result.get("score", 0.0), action=result.get("action", "archive"),
    )
    try:
        post_payload = {**payload, **result}
        result = {**result, **(hooks.fire(HookEvent.POST_CLASSIFY, post_payload) or {})}
    except Exception:
        pass

    # 8. PRE_REPLY hook for last-mile veto on auto replies.
    if result.get("action") == "auto_reply":
        try:
            payload2 = {**payload, **result}
            payload2 = hooks.fire(HookEvent.PRE_REPLY, payload2)
            if payload2.get("_vetoed"):
                result["action"] = "archive"
                result["auto_reply_text"] = ""
                result["reason"] = (result.get("reason") or "") + " | reply_vetoed"
        except Exception:
            pass

    return result
