"""Pre-execution safety scanner for tool calls.

Inspired by Claude Code's two-stage YOLO classifier:
- Stage 1: Fast keyword scan (< 1ms)
- Stage 2: LLM-based reasoning (only if Stage 1 flags risk)

Tools are categorized as:
- readonly: safe to auto-approve
- mutating: requires confirmation in strict mode
- destructive: always requires confirmation
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pilot.harness.safety")


class RiskLevel(Enum):
    SAFE = "safe"
    REVIEW = "review"
    BLOCK = "block"


@dataclass
class ScanResult:
    level: RiskLevel
    reasons: List[str]
    tool: str
    auto_approved: bool = False

    def is_safe(self) -> bool:
        return self.level == RiskLevel.SAFE or self.auto_approved


DESTRUCTIVE_PATTERNS = [
    re.compile(r"(?i)delete|remove|drop|truncate|destroy"),
    re.compile(r"(?i)force.*push|hard.*reset"),
]

PII_PATTERNS = [
    re.compile(r"\b\d{11}\b"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    re.compile(r"\b\d{6}(?:19|20)\d{8}\b"),
]

READONLY_TOOLS = {"im.fetch_thread", "voice.transcribe", "mentor.clarify", "mentor.summarize"}


def scan_tool_call(tool: str, args: Dict[str, Any]) -> ScanResult:
    reasons: List[str] = []

    if tool in READONLY_TOOLS:
        return ScanResult(level=RiskLevel.SAFE, reasons=[], tool=tool, auto_approved=True)

    args_str = str(args)

    for pat in DESTRUCTIVE_PATTERNS:
        if pat.search(args_str):
            reasons.append(f"destructive pattern: {pat.pattern}")

    for pat in PII_PATTERNS:
        if pat.search(args_str):
            reasons.append(f"potential PII detected: {pat.pattern}")

    if reasons:
        has_destructive = any("destructive" in r for r in reasons)
        level = RiskLevel.BLOCK if has_destructive else RiskLevel.REVIEW
        return ScanResult(level=level, reasons=reasons, tool=tool)

    return ScanResult(level=RiskLevel.SAFE, reasons=[], tool=tool, auto_approved=True)
