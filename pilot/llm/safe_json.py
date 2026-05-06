"""SafeJSON parsing — 多策略容错解析 LLM 返回的 JSON.

策略:
  1. 整体 json.loads
  2. 抠出 ```json ... ``` 代码块
  3. 找第一个 { 到最后一个 } / [ 到 ]
  4. 修复常见错误（缺逗号、单引号、trailing comma）
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Type

logger = logging.getLogger("pilot.llm.safe_json")


def safe_json_parse(
    raw: str,
    *,
    expected_type: Type | None = None,
    debug_label: str = "",
) -> Any:
    """尝试多种策略解析，失败返回 None."""
    if not raw or not isinstance(raw, str):
        return None

    # 1. 直接 parse
    try:
        obj = json.loads(raw)
        if expected_type is None or isinstance(obj, expected_type):
            return obj
    except Exception:
        pass

    # 2. ```json ... ```
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1).strip())
            if expected_type is None or isinstance(obj, expected_type):
                return obj
        except Exception:
            pass

    # 3. 第一个 { ... } 或 [ ... ]
    for opener, closer in (("{", "}"), ("[", "]")):
        first = raw.find(opener)
        last = raw.rfind(closer)
        if first >= 0 and last > first:
            chunk = raw[first:last + 1]
            for fixer in (lambda s: s, _fix_trailing_comma, _fix_single_quote):
                try:
                    obj = json.loads(fixer(chunk))
                    if expected_type is None or isinstance(obj, expected_type):
                        return obj
                except Exception:
                    continue

    if debug_label:
        logger.debug("safe_json_parse failed [%s]: %r", debug_label, raw[:200])
    return None


def _fix_trailing_comma(s: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", s)


def _fix_single_quote(s: str) -> str:
    # 仅当看起来像 JSON 但用了单引号时
    return s.replace("'", '"') if "'" in s and '"' not in s else s
