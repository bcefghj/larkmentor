"""Regex-based PII scrubber. Lightweight, no external dependencies.

For the LarkMentor scope this catches the everyday risks: phone number,
mainland-China ID card, email, bank card, and Feishu ``ou_`` open_id (since
those should never travel into a third-party LLM payload).

When the codebase later wants more coverage, swap in ``presidio-analyzer``
behind the same ``scrub_pii`` API – the report shape is identical.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class PIIReport:
    redacted_text: str
    counts: Dict[str, int] = field(default_factory=dict)
    spans: List[tuple[int, int, str]] = field(default_factory=list)


_PATTERNS: List[tuple[str, re.Pattern[str], str]] = [
    ("phone_cn", re.compile(r"\b1[3-9]\d{9}\b"), "[PHONE]"),
    ("idcard_cn", re.compile(r"\b[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b"), "[IDCARD]"),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
    ("bankcard", re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[BANKCARD]"),
    ("open_id", re.compile(r"\bou_[A-Za-z0-9]{20,}\b"), "[OPEN_ID]"),
    ("union_id", re.compile(r"\bon_[A-Za-z0-9]{20,}\b"), "[UNION_ID]"),
    ("user_id", re.compile(r"\buser_id\s*[:=]\s*\"?\w+\"?", re.IGNORECASE), "[USER_ID]"),
]


def scrub_pii(text: str) -> PIIReport:
    """Return text with PII replaced and a usage report."""
    if not text:
        return PIIReport(redacted_text=text or "")
    out = text
    counts: Dict[str, int] = {}
    spans: List[tuple[int, int, str]] = []
    for label, pattern, replacement in _PATTERNS:
        # Walk matches on the *original* text for span reporting.
        for m in pattern.finditer(text):
            spans.append((m.start(), m.end(), label))
        new_out, n = pattern.subn(replacement, out)
        if n:
            counts[label] = counts.get(label, 0) + n
        out = new_out
    spans.sort()
    return PIIReport(redacted_text=out, counts=counts, spans=spans)


def has_pii(text: str) -> bool:
    """Quick boolean test."""
    if not text:
        return False
    for _, pattern, _ in _PATTERNS:
        if pattern.search(text):
            return True
    return False
