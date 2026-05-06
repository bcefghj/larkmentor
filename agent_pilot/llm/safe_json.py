"""Robust JSON parsing for LLM output – v13.

LLMs often emit JSON wrapped in markdown code fences, with trailing commas,
single-quoted strings, Chinese punctuation around braces, etc. This module
keeps trying progressively looser repair strategies until the parse succeeds
or all options are exhausted.

Usage:
    from agent_pilot.llm.safe_json import safe_json_parse

    obj = safe_json_parse(llm_output, expected_type=list)  # returns [] if parsing fails
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Type, Union

logger = logging.getLogger("agent_pilot.llm.safe_json")


_FENCE_RE = re.compile(r"```(?:json|JSON|)\s*([\s\S]*?)```")
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_SINGLE_QUOTE_KEY_RE = re.compile(r"([{,]\s*)'([^']+)'(\s*:)")
_SINGLE_QUOTE_VALUE_RE = re.compile(r":\s*'([^']*)'(\s*[,}\]])")
_PYTHON_LITERAL_RE = re.compile(r"\b(True|False|None)\b")
_PYTHON_TO_JSON = {"True": "true", "False": "false", "None": "null"}
_FULLWIDTH_PUNCT = {
    "，": ",",
    "：": ":",
    "「": '"',
    "」": '"',
    "『": '"',
    "』": '"',
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "【": "[",
    "】": "]",
    "（": "(",
    "）": ")",
}


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text


def _normalise_punct(text: str) -> str:
    out = text
    for full, ascii_char in _FULLWIDTH_PUNCT.items():
        out = out.replace(full, ascii_char)
    return out


def _pyliterals(text: str) -> str:
    return _PYTHON_LITERAL_RE.sub(lambda m: _PYTHON_TO_JSON[m.group(0)], text)


def _strip_trailing_commas(text: str) -> str:
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _quote_python_keys(text: str) -> str:
    """Convert {'key': val} → {"key": val}, both keys and string values."""
    out = _SINGLE_QUOTE_KEY_RE.sub(r'\1"\2"\3', text)
    out = _SINGLE_QUOTE_VALUE_RE.sub(r': "\1"\2', out)
    return out


def _extract_largest_json_block(text: str) -> Optional[str]:
    """Find the largest balanced [..] or {..} block in text."""
    candidates = []
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        stack = 0
        start = -1
        for i, c in enumerate(text):
            if c == open_ch:
                if stack == 0:
                    start = i
                stack += 1
            elif c == close_ch and stack > 0:
                stack -= 1
                if stack == 0 and start >= 0:
                    candidates.append((start, i + 1, text[start:i + 1]))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[1] - t[0], reverse=True)
    return candidates[0][2]


def safe_json_parse(
    raw: str,
    expected_type: Optional[Type] = None,
    *,
    debug_label: str = "",
) -> Union[dict, list]:
    """Try increasingly aggressive repair strategies to parse LLM JSON.

    :param raw: the raw LLM output
    :param expected_type: optional ``dict`` or ``list`` to validate the result
    :param debug_label: identifier for log messages
    :return: parsed dict/list, or empty container of ``expected_type``
    """
    if not raw or not raw.strip():
        return _empty(expected_type)

    text = raw.strip()
    strategies = [
        ("raw", lambda t: t),
        ("strip_fences", _strip_fences),
        ("largest_block", lambda t: _extract_largest_json_block(t) or t),
        ("normalise_punct", _normalise_punct),
        ("pyliterals", _pyliterals),
        ("strip_trailing", _strip_trailing_commas),
        ("quote_keys", _quote_python_keys),
    ]

    accumulator = text
    for name, transform in strategies:
        accumulator = transform(accumulator)
        try:
            obj = json.loads(accumulator)
            if expected_type and not isinstance(obj, expected_type):
                logger.debug("safe_json[%s]: parsed as %s but expected %s",
                             debug_label, type(obj).__name__, expected_type.__name__)
                continue
            return obj
        except (json.JSONDecodeError, ValueError):
            continue

    # Final desperate try: combine all transforms and try once
    final = text
    for _, transform in strategies:
        final = transform(final)
    try:
        obj = json.loads(final)
        if expected_type and not isinstance(obj, expected_type):
            return _empty(expected_type)
        return obj
    except (json.JSONDecodeError, ValueError):
        logger.warning("safe_json[%s]: all strategies failed for input: %r",
                       debug_label, raw[:200])
        return _empty(expected_type)


def _empty(expected_type: Optional[Type]) -> Union[dict, list]:
    if expected_type is list:
        return []
    return {}


__all__ = ["safe_json_parse"]
