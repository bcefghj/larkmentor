"""ToolSandbox · 8 层安全栈第 7 层

Per-tool allowlist of which Feishu API surfaces and external endpoints a
tool may invoke. Defense in depth on top of ``PermissionManager``: even if a
tool is permitted to run, it can only touch the Feishu API surfaces declared
in its sandbox profile.

Profiles are declarative and live in code (``DEFAULT_SANDBOX_PROFILES``)
or, optionally, ``data/tool_sandbox.json`` for ops-time overrides.

Use cases:
- ``mentor.write`` may call ``im.message.create`` to send the draft card,
  but must never call ``contact.user`` (no PII enumeration)
- ``shield.classify`` is read-only; cannot touch ``bitable``, ``docx``
- ``mentor.proactive_suggest`` cannot call ``im.urgent_app`` (no auto-page)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger("flowguard.security.sandbox")

ROOT = Path(__file__).resolve().parents[2]
SANDBOX_FILE = ROOT / "data" / "tool_sandbox.json"


# ── Default profiles for built-in tools ──────────────────────


DEFAULT_SANDBOX_PROFILES: Dict[str, Dict[str, List[str]]] = {
    # Smart Shield
    "shield.classify": {
        "feishu_api": ["im.message.read"],
        "external": [],
    },
    "shield.auto_reply": {
        "feishu_api": ["im.message.read", "im.message.reply"],
        "external": [],
    },
    "shield.reaction_ack": {
        "feishu_api": ["im.message.reaction"],
        "external": [],
    },
    "shield.urgent_app": {
        "feishu_api": ["im.message.urgent_app"],
        "external": [],
    },
    # Mentor 4 Skills
    "mentor.kb_search": {
        "feishu_api": [],
        "external": ["doubao.embedding"],
    },
    "mentor.write": {
        "feishu_api": ["im.message.create", "im.message.reply"],
        "external": ["doubao.chat"],
    },
    "mentor.task": {
        "feishu_api": ["im.message.create"],
        "external": ["doubao.chat"],
    },
    "mentor.review": {
        "feishu_api": ["im.message.create", "docx.document.write"],
        "external": ["doubao.chat"],
    },
    "mentor.proactive_suggest": {
        "feishu_api": ["im.message.create"],
        "external": ["doubao.chat"],
    },
    # Memory
    "memory.query": {
        "feishu_api": [],
        "external": [],
    },
    "memory.write_archival": {
        "feishu_api": ["bitable.app.create_record", "docx.document.write"],
        "external": [],
    },
    # Calendar / task
    "calendar.draft_busy": {
        "feishu_api": ["calendar.calendar.read", "calendar.event.list"],
        "external": [],
    },
    "calendar.create_busy": {
        "feishu_api": ["calendar.event.create"],
        "external": [],
    },
    "task.create_draft": {
        "feishu_api": [],
        "external": [],
    },
    "task.create_real": {
        "feishu_api": ["task.task.create"],
        "external": [],
    },
}


@dataclass
class SandboxProfile:
    tool: str
    feishu_api: Set[str] = field(default_factory=set)
    external: Set[str] = field(default_factory=set)

    @classmethod
    def from_dict(cls, tool: str, d: Dict[str, List[str]]) -> "SandboxProfile":
        return cls(
            tool=tool,
            feishu_api=set(d.get("feishu_api", [])),
            external=set(d.get("external", [])),
        )

    def to_dict(self) -> Dict[str, List[str]]:
        return {
            "feishu_api": sorted(self.feishu_api),
            "external": sorted(self.external),
        }


@dataclass
class SandboxDecision:
    allowed: bool
    tool: str
    api: str
    reason: str = ""

    def __bool__(self) -> bool:
        return self.allowed


class ToolSandbox:
    """Allowlist-based per-tool API gate."""

    def __init__(self) -> None:
        self._profiles: Dict[str, SandboxProfile] = {}
        for tool, d in DEFAULT_SANDBOX_PROFILES.items():
            self._profiles[tool] = SandboxProfile.from_dict(tool, d)

    # ── Configuration ───────────────────────────────────────

    def set_profile(self, profile: SandboxProfile) -> None:
        self._profiles[profile.tool] = profile

    def get_profile(self, tool: str) -> Optional[SandboxProfile]:
        return self._profiles.get(tool)

    def load_overrides_file(self, path: Path = SANDBOX_FILE) -> int:
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("sandbox overrides load failed: %s", e)
            return 0
        n = 0
        for tool, d in (data or {}).items():
            self.set_profile(SandboxProfile.from_dict(tool, d))
            n += 1
        return n

    # ── Decision ─────────────────────────────────────────────

    def check(self, tool: str, api: str, *, channel: str = "feishu_api") -> SandboxDecision:
        prof = self._profiles.get(tool)
        if prof is None:
            return SandboxDecision(
                allowed=False, tool=tool, api=api,
                reason="no_profile_fail_closed",
            )
        allowed_set = prof.feishu_api if channel == "feishu_api" else prof.external
        if api in allowed_set:
            return SandboxDecision(allowed=True, tool=tool, api=api, reason="ok")
        return SandboxDecision(
            allowed=False, tool=tool, api=api,
            reason=f"{channel}_not_in_allowlist",
        )

    # ── Introspection ────────────────────────────────────────

    def list_profiles(self) -> Dict[str, Dict[str, List[str]]]:
        return {t: p.to_dict() for t, p in self._profiles.items()}


_default: Optional[ToolSandbox] = None


def default_sandbox() -> ToolSandbox:
    global _default
    if _default is None:
        _default = ToolSandbox()
        _default.load_overrides_file()
    return _default


def check(tool: str, api: str, *, channel: str = "feishu_api") -> SandboxDecision:
    return default_sandbox().check(tool, api, channel=channel)
