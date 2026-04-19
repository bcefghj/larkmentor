"""Six-tier ``flow_memory.md`` resolver.

Inspired by Claude Code's CLAUDE.md hierarchy
(Managed / User / Project / Local / AutoMemory / TeamMemory). For the
office-collaboration domain we map the tiers to organisational scopes:

    1. Enterprise   ── platform admin: company-wide guardrails
    2. Workspace    ── tenant-level defaults (whitelist domains, urgency rules)
    3. Department   ── department-specific style (engineering vs HR voice)
    4. Group        ── per-chat overrides (a specific Feishu group)
    5. User         ── personal preferences and learned bias
    6. Session      ── ephemeral notes for the current focus session

Each tier is a markdown file. Lower tiers override higher-tier directives.
The resolver returns one merged markdown string the caller can paste into
the system prompt as user-context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[2]
MEMORY_DIR = ROOT / "data" / "flow_memory_md"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("flowguard.memory.md")


TIER_ORDER = ["enterprise", "workspace", "department", "group", "user", "session"]


@dataclass
class TierFile:
    tier: str
    path: Path
    content: str


def _read(p: Path) -> str:
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def resolve_memory_md(
    *,
    enterprise_id: str = "default",
    workspace_id: str = "default",
    department_id: Optional[str] = None,
    group_id: Optional[str] = None,
    user_open_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Merge available tiers into one markdown blob.

    Each tier shows up under a level-1 heading so the LLM can keep them
    distinguished. Missing tiers are silently skipped.
    """
    pieces: List[str] = []
    candidates = [
        ("Enterprise", MEMORY_DIR / "enterprise" / f"{enterprise_id}.md"),
        ("Workspace", MEMORY_DIR / "workspace" / f"{workspace_id}.md"),
    ]
    if department_id:
        candidates.append(("Department", MEMORY_DIR / "department" / f"{department_id}.md"))
    if group_id:
        candidates.append(("Group", MEMORY_DIR / "group" / f"{group_id}.md"))
    if user_open_id:
        candidates.append(("User", MEMORY_DIR / "user" / f"{user_open_id}.md"))
    if session_id:
        candidates.append(("Session", MEMORY_DIR / "session" / f"{session_id}.md"))

    for label, path in candidates:
        body = _read(path)
        if body:
            pieces.append(f"# [{label}] {path.name}\n\n{body.strip()}\n")
    if not pieces:
        return ""
    return "\n---\n\n".join(pieces)


def write_tier(tier: str, identifier: str, body: str) -> Path:
    """Write a tier file. Returns the absolute path."""
    if tier not in TIER_ORDER:
        raise ValueError(f"unknown tier: {tier}")
    p = MEMORY_DIR / tier / f"{identifier}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p
