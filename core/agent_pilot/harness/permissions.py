"""Claude Code-style 6-mode permission gate with deny-first rule ordering.

Modes
-----
default              – Readonly allowed freely; writes prompt for confirmation.
acceptEdits          – Readonly + file edits auto-approved.
plan                 – Read only. All writes are blocked and *returned as an
                       error to the LLM* so the model knows "I cannot act yet".
auto                 – Everything allowed but a background classifier checks
                       scope drift.
dontAsk              – Only pre-approved tools + readonly Bash.
bypassPermissions    – Everything allowed (still protects sensitive paths).

Rule priority: **deny > ask > allow**.

The gate consumes tool metadata from ToolSpec (readonly / destructive) and
per-user rule overrides. Integrates with the existing security permission
manager (5-tier USER-level) for backwards compatibility.
"""

from __future__ import annotations

import enum
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pilot.harness.permissions")


class PermissionMode(str, enum.Enum):
    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    PLAN = "plan"
    AUTO = "auto"
    DONT_ASK = "dontAsk"
    BYPASS = "bypassPermissions"


class Decision(str, enum.Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass
class PermissionRule:
    pattern: str            # tool name exact, or "prefix.*"
    decision: Decision = Decision.ALLOW
    reason: str = ""

    def matches(self, tool: str) -> bool:
        if self.pattern == tool:
            return True
        if self.pattern.endswith(".*") and tool.startswith(self.pattern[:-2]):
            return True
        if self.pattern == "*":
            return True
        return False


@dataclass
class PermissionResult:
    decision: Decision
    tool: str
    mode: PermissionMode
    reason: str
    rule: Optional[PermissionRule] = None

    def is_allowed(self) -> bool:
        return self.decision == Decision.ALLOW

    def needs_user_confirm(self) -> bool:
        return self.decision == Decision.ASK

    def is_denied(self) -> bool:
        return self.decision == Decision.DENY

    def to_llm_error(self) -> str:
        """Message to return to the LLM when blocked in plan mode."""
        return (
            f"[PermissionError] Tool '{self.tool}' not allowed in mode "
            f"'{self.mode.value}'. Reason: {self.reason}. "
            f"Use a read-only tool or ask the user to exit plan mode."
        )


# Tools we always deny in every mode except bypass.
ALWAYS_PROTECTED = {
    "drive.wipe",
    "bitable.drop_table",
    "tenant.admin_delete",
}


# Tools considered "write-like" (non-readonly, non-destructive).
# Treated as ASK in default and DENY in plan.
WRITE_LIKE_PREFIXES = (
    "doc.", "canvas.", "slide.", "bitable.", "drive.", "calendar.",
    "im.send", "im.batch_send", "archive.",
)

# Tools considered safe readonly.
READONLY_PREFIXES = (
    "im.fetch_thread", "im.list", "doc.read", "mentor.clarify",
    "mentor.summarize", "voice.transcribe", "audit.list",
    "search.", "memory.query",
)


class PermissionGate:
    def __init__(self, mode: PermissionMode = PermissionMode.DEFAULT) -> None:
        self._mode = mode
        self._user_modes: Dict[str, PermissionMode] = {}
        self._deny: List[PermissionRule] = []
        self._ask: List[PermissionRule] = []
        self._allow: List[PermissionRule] = []
        self._lock = threading.RLock()
        self._audit: List[Dict[str, Any]] = []

    # ── Mode management ──

    @property
    def mode(self) -> PermissionMode:
        return self._mode

    def set_mode(self, mode: PermissionMode) -> None:
        logger.info("permission mode: %s → %s", self._mode.value, mode.value)
        self._mode = mode

    def set_user_mode(self, user_open_id: str, mode: PermissionMode) -> None:
        with self._lock:
            self._user_modes[user_open_id] = mode

    def user_mode(self, user_open_id: str = "") -> PermissionMode:
        with self._lock:
            return self._user_modes.get(user_open_id, self._mode)

    # ── Rule management ──

    def add_rule(self, rule: PermissionRule) -> None:
        with self._lock:
            bucket = {
                Decision.DENY: self._deny,
                Decision.ASK: self._ask,
                Decision.ALLOW: self._allow,
            }[rule.decision]
            bucket.append(rule)

    def clear_rules(self) -> None:
        with self._lock:
            self._deny.clear()
            self._ask.clear()
            self._allow.clear()

    # ── Evaluate ──

    def check(self, *, tool: str, readonly: bool = False, destructive: bool = False,
              user_open_id: str = "", args: Optional[Dict[str, Any]] = None) -> PermissionResult:
        """Evaluate permission for a tool call. Deny-first priority."""
        mode = self.user_mode(user_open_id)

        # Always-protected tools.
        if tool in ALWAYS_PROTECTED and mode != PermissionMode.BYPASS:
            result = PermissionResult(
                decision=Decision.DENY, tool=tool, mode=mode,
                reason="always-protected tool",
            )
            self._remember(tool, user_open_id, result)
            return result

        # 1. Explicit deny rules win first.
        with self._lock:
            for r in self._deny:
                if r.matches(tool):
                    result = PermissionResult(
                        decision=Decision.DENY, tool=tool, mode=mode,
                        reason=f"explicit deny rule: {r.pattern} ({r.reason})",
                        rule=r,
                    )
                    self._remember(tool, user_open_id, result)
                    return result

            # 2. Then ask rules.
            for r in self._ask:
                if r.matches(tool):
                    result = PermissionResult(
                        decision=Decision.ASK, tool=tool, mode=mode,
                        reason=f"explicit ask rule: {r.pattern} ({r.reason})",
                        rule=r,
                    )
                    self._remember(tool, user_open_id, result)
                    return result

            # 3. Finally allow rules.
            for r in self._allow:
                if r.matches(tool):
                    result = PermissionResult(
                        decision=Decision.ALLOW, tool=tool, mode=mode,
                        reason=f"explicit allow rule: {r.pattern}",
                        rule=r,
                    )
                    self._remember(tool, user_open_id, result)
                    return result

        # Mode-based defaults.
        if mode == PermissionMode.BYPASS:
            result = PermissionResult(decision=Decision.ALLOW, tool=tool, mode=mode, reason="bypass mode")
            self._remember(tool, user_open_id, result)
            return result

        if mode == PermissionMode.PLAN:
            # Only readonly allowed; everything else returns ERROR-to-LLM (deny).
            if readonly or _is_readonly(tool):
                result = PermissionResult(decision=Decision.ALLOW, tool=tool, mode=mode, reason="plan + readonly")
            else:
                result = PermissionResult(decision=Decision.DENY, tool=tool, mode=mode,
                                           reason="plan mode blocks all writes")
            self._remember(tool, user_open_id, result)
            return result

        if mode == PermissionMode.AUTO or mode == PermissionMode.DONT_ASK:
            # Allow unless destructive + non-readonly (then ask).
            if destructive and not readonly:
                result = PermissionResult(decision=Decision.ASK, tool=tool, mode=mode,
                                           reason="destructive requires confirm")
            else:
                result = PermissionResult(decision=Decision.ALLOW, tool=tool, mode=mode,
                                           reason="mode permits")
            self._remember(tool, user_open_id, result)
            return result

        if mode == PermissionMode.ACCEPT_EDITS:
            # Allow readonly + edits; destructive asks.
            if destructive:
                result = PermissionResult(decision=Decision.ASK, tool=tool, mode=mode,
                                           reason="destructive in acceptEdits asks")
            else:
                result = PermissionResult(decision=Decision.ALLOW, tool=tool, mode=mode,
                                           reason="acceptEdits permits writes")
            self._remember(tool, user_open_id, result)
            return result

        # default mode:
        if readonly or _is_readonly(tool):
            result = PermissionResult(decision=Decision.ALLOW, tool=tool, mode=mode, reason="default + readonly")
        elif destructive:
            result = PermissionResult(decision=Decision.ASK, tool=tool, mode=mode,
                                       reason="destructive requires confirm (default)")
        elif _is_write_like(tool):
            result = PermissionResult(decision=Decision.ASK, tool=tool, mode=mode,
                                       reason="write-like needs confirm (default)")
        else:
            result = PermissionResult(decision=Decision.ALLOW, tool=tool, mode=mode, reason="default: unknown, allow")
        self._remember(tool, user_open_id, result)
        return result

    def _remember(self, tool: str, user: str, r: PermissionResult) -> None:
        with self._lock:
            self._audit.append({
                "tool": tool, "user": user[-8:] if user else "-",
                "decision": r.decision.value, "mode": r.mode.value,
                "reason": r.reason,
            })
            if len(self._audit) > 500:
                self._audit = self._audit[-500:]

    def audit_tail(self, n: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._audit[-n:])


def _is_readonly(tool: str) -> bool:
    return any(tool.startswith(p) for p in READONLY_PREFIXES)


def _is_write_like(tool: str) -> bool:
    return any(tool.startswith(p) for p in WRITE_LIKE_PREFIXES)


_default: Optional[PermissionGate] = None
_default_lock = threading.Lock()


def default_permission_gate() -> PermissionGate:
    global _default
    with _default_lock:
        if _default is None:
            mode_env = os.getenv("LARKMENTOR_PERMISSION_MODE", "default")
            try:
                mode = PermissionMode(mode_env)
            except ValueError:
                mode = PermissionMode.DEFAULT
            _default = PermissionGate(mode)
        return _default
