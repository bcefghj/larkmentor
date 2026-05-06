"""4 级权限策略：deny → allow → classifier → ask（Claude Code 风格）.

每次工具调用前依次判定:
  1. deny rules: 命中即拒绝（最高优先级）
  2. allow rules: 命中即放行
  3. classifier: 启发式（看是否 destructive、是否带敏感参数）
  4. ask user: 走 governance.approval 弹卡片二次确认
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from pilot.runtime.session import Session

logger = logging.getLogger("pilot.governance.policy")


@dataclass
class PermissionDecision:
    verdict: str  # "allow" | "deny" | "ask"
    reason: str = ""
    require_human: bool = False


# ── 默认策略集 ──


# Deny 优先级最高
DEFAULT_DENY_RULES: list[dict[str, Any]] = [
    {"tool_pattern": r"^os\..*", "reason": "禁止直接 os 调用"},
    {"tool_pattern": r"^subprocess\..*", "reason": "禁止 subprocess"},
    {"tool_pattern": r"^.*rm.*", "input_field": "path", "input_pattern": r"^/(etc|var|usr|opt|root)/", "reason": "禁止删除系统目录"},
]

# Allow 白名单
DEFAULT_ALLOW_RULES: list[dict[str, Any]] = [
    {"tool_pattern": r"^doc\.create"},
    {"tool_pattern": r"^doc\.append"},
    {"tool_pattern": r"^canvas\.create"},
    {"tool_pattern": r"^canvas\.add_shape"},
    {"tool_pattern": r"^slide\.generate"},
    {"tool_pattern": r"^slide\.rehearse"},
    {"tool_pattern": r"^archive\.bundle"},
    {"tool_pattern": r"^im\..*"},
    {"tool_pattern": r"^voice\..*"},
    {"tool_pattern": r"^mentor\..*"},
    {"tool_pattern": r"^bitable\..*"},
    {"tool_pattern": r"^sync\..*"},
]

# Destructive 工具（默认需 ask）
DESTRUCTIVE_TOOLS = {
    "doc.delete",
    "drive.delete",
    "bitable.record_delete",
}


class PermissionGate:
    def __init__(
        self,
        *,
        deny_rules: list[dict[str, Any]] | None = None,
        allow_rules: list[dict[str, Any]] | None = None,
        require_approval_for_destructive: bool = True,
    ) -> None:
        self.deny_rules = deny_rules if deny_rules is not None else DEFAULT_DENY_RULES
        self.allow_rules = allow_rules if allow_rules is not None else DEFAULT_ALLOW_RULES
        self.require_approval_for_destructive = require_approval_for_destructive

    async def check(
        self,
        *,
        session: Session,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> PermissionDecision:
        # 1. deny
        for rule in self.deny_rules:
            if self._match_rule(rule, tool_name, tool_input):
                return PermissionDecision(verdict="deny", reason=rule.get("reason", "denied by policy"))

        # 2. allow
        for rule in self.allow_rules:
            if self._match_rule(rule, tool_name, tool_input):
                # destructive 即使 allow 也要 ask
                if self.require_approval_for_destructive and tool_name in DESTRUCTIVE_TOOLS:
                    return PermissionDecision(verdict="ask", reason="destructive tool requires approval", require_human=True)
                return PermissionDecision(verdict="allow", reason="allow-listed")

        # 3. classifier
        if self._is_destructive(tool_name, tool_input):
            return PermissionDecision(verdict="ask", reason="classifier: destructive intent", require_human=True)
        if tool_name in DESTRUCTIVE_TOOLS:
            return PermissionDecision(verdict="ask", reason="destructive tool", require_human=True)

        # 4. ask（默认未知工具拒绝）
        return PermissionDecision(verdict="deny", reason=f"未列入 allow-list 的工具: {tool_name}")

    @staticmethod
    def _match_rule(rule: dict[str, Any], tool_name: str, tool_input: dict[str, Any]) -> bool:
        pat = rule.get("tool_pattern", "")
        if pat and not re.search(pat, tool_name):
            return False
        field = rule.get("input_field", "")
        ipat = rule.get("input_pattern", "")
        if field and ipat:
            val = tool_input.get(field, "")
            if not isinstance(val, str) or not re.search(ipat, val):
                return False
        return True

    @staticmethod
    def _is_destructive(tool_name: str, tool_input: dict[str, Any]) -> bool:
        if any(k in tool_name.lower() for k in ("delete", "remove", "drop", "wipe", "purge")):
            return True
        for v in tool_input.values():
            if isinstance(v, str) and any(k in v.lower() for k in ("rm -rf", "drop table")):
                return True
        return False


_default: PermissionGate | None = None


def default_gate() -> PermissionGate:
    global _default
    if _default is None:
        _default = PermissionGate(
            require_approval_for_destructive=os.getenv("DESTRUCTIVE_TOOL_REQUIRE_APPROVAL", "1") == "1",
        )
    return _default
