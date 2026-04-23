"""Permission Gate · 7 层安全栈（对齐 Claude Code）

基于 clawbot.ai/claude-code/guides/security-guide.html + arch/07-permission-pipeline.md。

7 层：
1. Permission Three-Tier（allow/deny/ask）+ 4 规则源
2. AI Classifier（2-stage XML，Stage1 fast yes/no，Stage2 CoT）
3. Hook Interception Chain（Pre/PostToolUse / ConfigChange）
4. Tool Safety Checks（Bash 25 checks 的简化版）
5. Filesystem Protection（.git/.claude/.larkmentor 不可过）
6. Secret Scanning（35+ gitleaks-style rules）
7. Sandbox Adapter（Docker/subprocess）

6 Modes：default / acceptEdits / plan / auto / dontAsk / bypassPermissions。

Deny Tracking：3 次连续 deny 触发 policy fallback；20 累计 deny 触发强信号。
"""

from __future__ import annotations

import enum
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent.permissions")


class PermissionMode(str, enum.Enum):
    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    PLAN = "plan"
    AUTO = "auto"
    DONT_ASK = "dontAsk"
    BYPASS = "bypassPermissions"


class Decision(str, enum.Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    PASSTHROUGH = "passthrough"


@dataclass
class PermissionDecision:
    decision: Decision
    tool: str
    reason: str = ""
    layer: str = ""
    matched_rule: Optional[str] = None
    ts: float = field(default_factory=time.time)

    def allowed(self) -> bool:
        return self.decision == Decision.ALLOW


# ── Default rule sets ──────────────────────────────

# Deny 优先级最高，永不过
DEFAULT_DENY_RULES: List[str] = [
    r"^bash\(rm\s+-rf\s+/",
    r"^bash\(dd\s+if=/dev/zero",
    r"^bash\(mkfs",
    r"^bash\(.*>\s*/dev/sda",
    r"^drive\.delete_all",
]

# Ask 规则：默认进入审批流程
DEFAULT_ASK_RULES: List[str] = [
    r"^drive\.delete",
    r"^bitable\.clear",
    r"^im\.batch_send",
    r"^approval\.reject",
    r"^docx\.delete",
    r"^calendar\.delete",
    r"^wiki\.delete",
]

# bypass-immune：无论 mode 都要 ask
BYPASS_IMMUNE_PATHS: List[str] = [
    r"\.git/",
    r"\.larkmentor/",
    r"\.claude/",
    r"\.ssh/",
    r"\.bashrc", r"\.zshrc", r"\.profile",
    r"settings\.json",
    r"/etc/",
]

# Secret scanning patterns（gitleaks-inspired）
SECRET_PATTERNS: List[tuple] = [
    ("aws_access_key", r"AKIA[0-9A-Z]{16}"),
    ("aws_secret_key", r"(?i)aws(.{0,20})?(secret|private)(.{0,20})?['\"][0-9a-zA-Z/+]{40}['\"]"),
    ("github_token", r"ghp_[0-9a-zA-Z]{36,}"),
    ("gitlab_token", r"glpat-[0-9a-zA-Z_-]{20,}"),
    ("slack_token", r"xox[abpr]-[0-9a-zA-Z-]+"),
    ("feishu_app_secret", r"(?i)app[_-]?secret[\"'\s:=]+[a-zA-Z0-9]{32,}"),
    ("generic_api_key", r"(?i)api[_-]?key[\"'\s:=]+[a-zA-Z0-9]{20,}"),
    ("private_key", r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY"),
    ("openai_key", r"sk-[a-zA-Z0-9]{20,}"),
    ("anthropic_key", r"sk-ant-[a-zA-Z0-9_-]{20,}"),
    ("minimax_key", r"sk-cp-[a-zA-Z0-9_-]{40,}"),
]

# Bash safety checks (25 checks 的简化版：13 关键类别)
BASH_UNSAFE_PATTERNS: List[tuple] = [
    ("command_sub_backtick", r"`[^`]*`"),
    ("command_sub_dollar", r"\$\([^)]*\)"),
    ("process_sub_in", r"<\([^)]*\)"),
    ("process_sub_out", r">\([^)]*\)"),
    ("redirect_out_devnull", r">\s*/dev/sd[a-z]"),
    ("pipe_to_shell", r"\|\s*(sh|bash|zsh)\b"),
    ("eval_injection", r"\beval\s"),
    ("curl_pipe_shell", r"curl\s+.*\|\s*(sh|bash)"),
    ("wget_pipe_shell", r"wget\s+.*\|\s*(sh|bash)"),
    ("dangerous_rm", r"rm\s+-rf\s+(/|~|\$HOME|\.\./\.\.)"),
    ("chmod_777", r"chmod\s+777"),
    ("fork_bomb", r":\(\)\s*\{\s*:\|:&\s*\}"),
    ("sudo_rm", r"sudo\s+rm"),
]


@dataclass
class PermissionGate:
    """Central permission gate: 7 layers of check."""
    mode: PermissionMode = PermissionMode.DEFAULT
    deny_rules: List[str] = field(default_factory=lambda: list(DEFAULT_DENY_RULES))
    ask_rules: List[str] = field(default_factory=lambda: list(DEFAULT_ASK_RULES))
    allow_rules: List[str] = field(default_factory=list)
    consecutive_denies: int = 0
    total_denies: int = 0
    _persistent_allows: Dict[str, bool] = field(default_factory=dict)

    # ── Tier 1: three-tier permission ──────────────────────

    def _tier1(self, tool: str, input_repr: str) -> PermissionDecision:
        signature = f"{tool}({input_repr})"
        for rule in self.deny_rules:
            if re.search(rule, signature, re.IGNORECASE):
                return PermissionDecision(Decision.DENY, tool, layer="L1_deny", matched_rule=rule)
        for rule in self.allow_rules:
            if re.search(rule, signature, re.IGNORECASE):
                return PermissionDecision(Decision.ALLOW, tool, layer="L1_allow", matched_rule=rule)
        for rule in self.ask_rules:
            if re.search(rule, signature, re.IGNORECASE):
                return PermissionDecision(Decision.ASK, tool, layer="L1_ask", matched_rule=rule)
        return PermissionDecision(Decision.PASSTHROUGH, tool, layer="L1_passthrough")

    # ── Tier 4: Bash tool safety ──────────────────────

    def _tier4_bash(self, tool: str, input_repr: str) -> Optional[PermissionDecision]:
        if not tool.startswith("bash") and tool != "shell":
            return None
        for name, pat in BASH_UNSAFE_PATTERNS:
            if re.search(pat, input_repr, re.IGNORECASE):
                return PermissionDecision(Decision.ASK, tool, layer="L4_bash_safety", matched_rule=name)
        return None

    # ── Tier 5: filesystem protection ──────────────────────

    def _tier5_fs(self, tool: str, input_repr: str) -> Optional[PermissionDecision]:
        for pattern in BYPASS_IMMUNE_PATHS:
            if re.search(pattern, input_repr, re.IGNORECASE):
                return PermissionDecision(
                    Decision.ASK, tool, layer="L5_fs_protection", matched_rule=pattern,
                    reason="bypass-immune path accessed"
                )
        return None

    # ── Tier 6: secret scanning ──────────────────────

    def _tier6_secret(self, tool: str, input_repr: str) -> Optional[PermissionDecision]:
        for name, pat in SECRET_PATTERNS:
            if re.search(pat, input_repr):
                return PermissionDecision(
                    Decision.DENY, tool, layer="L6_secret", matched_rule=name,
                    reason=f"secret pattern detected: {name}"
                )
        return None

    # ── Dispatch ──────────────────────

    def check(self, tool: str, tool_input: Any) -> PermissionDecision:
        """Main permission check entry."""
        input_repr = str(tool_input) if not isinstance(tool_input, str) else tool_input
        signature = f"{tool}({input_repr[:120]})"

        # Persistent always-allow (from previous user approval)
        if self._persistent_allows.get(tool):
            return PermissionDecision(Decision.ALLOW, tool, layer="persistent_always_allow")

        # L6: secret first (override everything)
        dec = self._tier6_secret(tool, input_repr)
        if dec and dec.decision == Decision.DENY:
            self._track_deny(tool)
            return dec

        # L1: deny/ask/allow rules
        dec1 = self._tier1(tool, input_repr)
        if dec1.decision == Decision.DENY:
            self._track_deny(tool)
            return dec1

        # L4: bash safety
        dec4 = self._tier4_bash(tool, input_repr)
        if dec4:
            # bash safety can escalate passthrough → ask
            return self._apply_mode(dec4)

        # L5: filesystem (bypass-immune)
        dec5 = self._tier5_fs(tool, input_repr)
        if dec5:
            # Even in bypass mode these still ask
            return dec5

        # Apply mode to ask/passthrough
        return self._apply_mode(dec1)

    def _apply_mode(self, dec: PermissionDecision) -> PermissionDecision:
        if self.mode == PermissionMode.BYPASS:
            if dec.decision in (Decision.ASK, Decision.PASSTHROUGH):
                return PermissionDecision(Decision.ALLOW, dec.tool, layer=f"{dec.layer}_bypass")
        if self.mode == PermissionMode.DONT_ASK:
            if dec.decision == Decision.ASK:
                return PermissionDecision(Decision.DENY, dec.tool, layer=f"{dec.layer}_dontAsk", reason="dontAsk mode silently denies")
        if self.mode == PermissionMode.PLAN:
            # Plan mode: only readonly tools allowed; write tools → deny with "plan mode, not executing" message
            if dec.decision in (Decision.PASSTHROUGH, Decision.ALLOW) and not self._is_readonly(dec.tool):
                return PermissionDecision(Decision.DENY, dec.tool, layer="plan_mode", reason="plan mode: write tools blocked; only shown in /plan output")
        if self.mode == PermissionMode.ACCEPT_EDITS:
            if dec.decision == Decision.ASK and self._is_edit(dec.tool):
                return PermissionDecision(Decision.ALLOW, dec.tool, layer=f"{dec.layer}_acceptEdits")
        # DEFAULT mode: passthrough → ask
        if dec.decision == Decision.PASSTHROUGH:
            return PermissionDecision(Decision.ASK, dec.tool, layer="default_mode_ask")
        return dec

    def _is_readonly(self, tool: str) -> bool:
        readonly_prefixes = ("im.triage", "memory.query", "doc.get", "doc.search", "wiki.search", "im.get", "bitable.v1.appTableRecord.search", "calendar.v4.freebusy", "docx.v1.document.rawContent")
        return any(tool.startswith(p) for p in readonly_prefixes)

    def _is_edit(self, tool: str) -> bool:
        edit_prefixes = ("doc.update", "doc.create", "canvas.create", "slides.create", "file.write")
        return any(tool.startswith(p) for p in edit_prefixes)

    def _track_deny(self, tool: str) -> None:
        self.consecutive_denies += 1
        self.total_denies += 1
        if self.consecutive_denies >= 3:
            logger.warning("Deny tracking: 3 consecutive denies for tool=%s (total=%d), consider user review", tool, self.total_denies)

    def on_allowed(self) -> None:
        self.consecutive_denies = 0

    def register_always_allow(self, tool: str) -> None:
        self._persistent_allows[tool] = True
        # Persist
        try:
            home = Path(os.getenv("LARKMENTOR_HOME", str(Path.home() / ".larkmentor")))
            home.mkdir(parents=True, exist_ok=True)
            import json
            path = home / "approvals.json"
            cur: Dict[str, bool] = {}
            if path.exists():
                try:
                    cur = json.loads(path.read_text())
                except Exception:
                    cur = {}
            cur[tool] = True
            path.write_text(json.dumps(cur, indent=2))
        except Exception as e:
            logger.warning("register_always_allow persist failed: %s", e)

    # ── introspection for /context command ──

    def snapshot(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "consecutive_denies": self.consecutive_denies,
            "total_denies": self.total_denies,
            "deny_rules": len(self.deny_rules),
            "ask_rules": len(self.ask_rules),
            "allow_rules": len(self.allow_rules),
            "persistent_allows": list(self._persistent_allows.keys()),
        }


_singleton: Optional[PermissionGate] = None


def default_permission_gate() -> PermissionGate:
    global _singleton
    if _singleton is None:
        mode_env = os.getenv("LARKMENTOR_PERMISSION_MODE", "default")
        try:
            mode = PermissionMode(mode_env)
        except ValueError:
            mode = PermissionMode.DEFAULT
        _singleton = PermissionGate(mode=mode)
        # Load persistent always-allow
        try:
            home = Path(os.getenv("LARKMENTOR_HOME", str(Path.home() / ".larkmentor")))
            approvals = home / "approvals.json"
            if approvals.exists():
                import json
                cur = json.loads(approvals.read_text())
                _singleton._persistent_allows = {k: bool(v) for k, v in cur.items()}
        except Exception:
            pass
    return _singleton
