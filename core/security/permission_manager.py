"""Five-tier permission gate.

Each FlowGuard tool declares the minimum permission level required to run.
Users sit at one of:

    READ_ONLY    – can observe but never sends or writes
    SAFE_REPLY   – can auto-reply with the [FlowGuard代回复] tag (P2)
    DRAFT_ACTION – can prepare drafts/tasks/calendar entries that need approval
    SEND_ACTION  – can send messages, create Bitable rows, write docs
    YOLO         – everything goes (only used for E2E tests)

Decisions are deny-by-default. The manager logs all deny events to audit_log.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger("flowguard.security.permission")


class PermissionLevel(enum.IntEnum):
    READ_ONLY = 0
    SAFE_REPLY = 1
    DRAFT_ACTION = 2
    SEND_ACTION = 3
    YOLO = 99


# Default per-user permission profile.
DEFAULT_USER_LEVEL = PermissionLevel.SEND_ACTION

# Per-tool minimum level. Add new tools here as you create them.
TOOL_MIN_LEVEL: Dict[str, PermissionLevel] = {
    # Observers
    "shield.classify": PermissionLevel.READ_ONLY,
    "memory.query": PermissionLevel.READ_ONLY,
    "audit.list": PermissionLevel.READ_ONLY,
    # Replies
    "shield.auto_reply": PermissionLevel.SAFE_REPLY,
    "shield.reaction_ack": PermissionLevel.SAFE_REPLY,
    # Drafts
    "rookie.review_draft": PermissionLevel.DRAFT_ACTION,
    "review.weekly_draft": PermissionLevel.DRAFT_ACTION,
    "calendar.draft_busy": PermissionLevel.DRAFT_ACTION,
    "task.create_draft": PermissionLevel.DRAFT_ACTION,
    # Side-effects
    "shield.urgent_app": PermissionLevel.SEND_ACTION,
    "shield.urgent_sms": PermissionLevel.SEND_ACTION,
    "shield.urgent_phone": PermissionLevel.SEND_ACTION,
    "review.publish_doc": PermissionLevel.SEND_ACTION,
    "memory.write_archival": PermissionLevel.SEND_ACTION,
    "calendar.create_busy": PermissionLevel.SEND_ACTION,
    "task.create_real": PermissionLevel.SEND_ACTION,
    # ── v4 Mentor tools ──
    "mentor.kb_search": PermissionLevel.READ_ONLY,
    "mentor.write": PermissionLevel.DRAFT_ACTION,
    "mentor.task": PermissionLevel.DRAFT_ACTION,
    "mentor.review": PermissionLevel.DRAFT_ACTION,
    "mentor.proactive_suggest": PermissionLevel.DRAFT_ACTION,
}


@dataclass
class PermissionDecision:
    allowed: bool
    tool: str
    user: str
    user_level: PermissionLevel
    required: PermissionLevel
    reason: str


class PermissionManager:
    """Holds per-user permission level overrides and adjudicates calls."""

    def __init__(self) -> None:
        self._user_levels: Dict[str, PermissionLevel] = {}

    def set_user_level(self, open_id: str, level: PermissionLevel) -> None:
        self._user_levels[open_id] = level

    def get_user_level(self, open_id: str) -> PermissionLevel:
        return self._user_levels.get(open_id, DEFAULT_USER_LEVEL)

    def check(self, *, tool: str, user_open_id: str) -> PermissionDecision:
        required = TOOL_MIN_LEVEL.get(tool, PermissionLevel.YOLO)
        # Unknown tools must declare their level explicitly → fail-closed.
        if tool not in TOOL_MIN_LEVEL:
            decision = PermissionDecision(
                allowed=False, tool=tool, user=user_open_id,
                user_level=self.get_user_level(user_open_id),
                required=required, reason="unknown_tool_fail_closed",
            )
            logger.warning("permission deny: unknown tool %s", tool)
            return decision
        actual = self.get_user_level(user_open_id)
        ok = actual >= required
        decision = PermissionDecision(
            allowed=ok, tool=tool, user=user_open_id,
            user_level=actual, required=required,
            reason="ok" if ok else "user_level_below_required",
        )
        if not ok:
            logger.info(
                "permission deny: tool=%s user=%s actual=%s required=%s",
                tool, user_open_id[-8:], actual.name, required.name,
            )
        return decision


_default_manager: Optional[PermissionManager] = None


def default_manager() -> PermissionManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = PermissionManager()
    return _default_manager
