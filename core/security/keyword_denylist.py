"""KeywordDenylist · 8 层安全栈第 5 层

A fast in-memory keyword/regex deny list applied to incoming user messages
before any LLM call. Designed for "high-risk content" patterns that should
be blocked regardless of LLM judgment:

- explicit prompt-injection markers ("ignore previous instructions", ...)
- secret-leak patterns ("My API key is sk-...")
- self-harm escalation that we want to escalate to human ops
- competitor secret keywords your org doesn't want sent to LLMs

Loaded from ``data/keyword_denylist.json`` if present; otherwise uses
defaults.

This module is part of the Anthropic-Claude-Code-inspired 8-layer security
stack (see ``core/security/__init__.py``).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("flowguard.security.denylist")

ROOT = Path(__file__).resolve().parents[2]
DENYLIST_FILE = ROOT / "data" / "keyword_denylist.json"


_DEFAULT_KEYWORDS: List[str] = [
    "ignore previous instructions",
    "ignore all previous instructions",
    "disregard the above",
    "you are now",
    "system prompt:",
    "<system>",
    "</system>",
    "<|im_start|>",
    "<|im_end|>",
    "DAN mode",
    "developer mode",
    "jailbreak",
]

_DEFAULT_REGEX: List[str] = [
    r"sk-[a-zA-Z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"-----BEGIN (RSA|EC|OPENSSH|PRIVATE) (PRIVATE )?KEY-----",
]


@dataclass
class DenyHit:
    matched: bool
    rule: str = ""
    kind: str = ""
    fragment: str = ""

    def __bool__(self) -> bool:
        return self.matched


@dataclass
class KeywordDenylist:
    keywords: List[str] = field(default_factory=lambda: list(_DEFAULT_KEYWORDS))
    regexes: List[str] = field(default_factory=lambda: list(_DEFAULT_REGEX))
    _compiled: List[re.Pattern] = field(default_factory=list, repr=False)
    case_insensitive: bool = True

    def __post_init__(self) -> None:
        flags = re.IGNORECASE if self.case_insensitive else 0
        self._compiled = []
        for r in self.regexes:
            try:
                self._compiled.append(re.compile(r, flags))
            except re.error as e:
                logger.warning("invalid regex skipped: %s (%s)", r, e)

    # ── Public API ───────────────────────────────────────────

    def check(self, text: str) -> DenyHit:
        if not text:
            return DenyHit(matched=False)
        haystack = text.lower() if self.case_insensitive else text
        for kw in self.keywords:
            needle = kw.lower() if self.case_insensitive else kw
            if needle and needle in haystack:
                return DenyHit(matched=True, rule=kw, kind="keyword", fragment=kw)
        for pat in self._compiled:
            m = pat.search(text)
            if m:
                return DenyHit(matched=True, rule=pat.pattern,
                               kind="regex", fragment=m.group(0)[:60])
        return DenyHit(matched=False)

    def add_keyword(self, kw: str) -> None:
        if kw and kw not in self.keywords:
            self.keywords.append(kw)

    def add_regex(self, pattern: str) -> None:
        try:
            flags = re.IGNORECASE if self.case_insensitive else 0
            self._compiled.append(re.compile(pattern, flags))
            self.regexes.append(pattern)
        except re.error as e:
            logger.warning("add_regex skipped: %s (%s)", pattern, e)

    def to_dict(self) -> dict:
        return {"keywords": self.keywords, "regexes": self.regexes,
                "case_insensitive": self.case_insensitive}

    @classmethod
    def from_dict(cls, d: dict) -> "KeywordDenylist":
        return cls(
            keywords=list(d.get("keywords", _DEFAULT_KEYWORDS)),
            regexes=list(d.get("regexes", _DEFAULT_REGEX)),
            case_insensitive=bool(d.get("case_insensitive", True)),
        )

    @classmethod
    def load_default(cls) -> "KeywordDenylist":
        if DENYLIST_FILE.exists():
            try:
                d = json.loads(DENYLIST_FILE.read_text(encoding="utf-8"))
                return cls.from_dict(d)
            except Exception as e:
                logger.warning("denylist load failed, using defaults: %s", e)
        return cls()


_default: Optional[KeywordDenylist] = None


def default_denylist() -> KeywordDenylist:
    global _default
    if _default is None:
        _default = KeywordDenylist.load_default()
    return _default


def check_text(text: str) -> Tuple[bool, str, str]:
    """Convenience wrapper. Returns ``(blocked, rule, kind)``."""
    hit = default_denylist().check(text)
    return bool(hit), hit.rule, hit.kind
