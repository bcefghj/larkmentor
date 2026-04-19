"""Lifecycle-hook system inspired by Claude Code's hook framework.

A hook is a callable registered against an event name. When the event fires,
all hooks run in registration order. A hook may:

* return ``None`` – no side-effect on the payload
* return a ``dict`` – replaces / merges into the payload
* raise ``HookVeto`` – aborts the event chain

Hooks can be registered programmatically or loaded from a JSON file at
``data/hooks.json`` so on-prem operators can plug in custom rules without
touching code.
"""

from __future__ import annotations

import enum
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("flowguard.security.hooks")


class HookEvent(enum.Enum):
    PRE_CLASSIFY = "pre_classify"
    POST_CLASSIFY = "post_classify"
    PRE_REPLY = "pre_reply"
    POST_REPLY = "post_reply"
    PRE_URGENT = "pre_urgent"
    PRE_TOOL_CALL = "pre_tool_call"
    POST_TOOL_CALL = "post_tool_call"
    PRE_LLM_CALL = "pre_llm_call"
    POST_LLM_CALL = "post_llm_call"


class HookVeto(Exception):
    """Raised by a hook to abort downstream processing."""


HookFn = Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]


class HookSystem:
    def __init__(self) -> None:
        self._hooks: Dict[HookEvent, List[HookFn]] = {ev: [] for ev in HookEvent}

    def register(self, event: HookEvent, fn: HookFn) -> None:
        self._hooks[event].append(fn)
        logger.info("hook registered: %s ← %s", event.value, getattr(fn, "__name__", repr(fn)))

    def fire(self, event: HookEvent, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run hooks. Returns the (possibly mutated) payload."""
        for fn in self._hooks.get(event, []):
            try:
                result = fn(payload)
                if isinstance(result, dict):
                    payload = {**payload, **result}
            except HookVeto as veto:
                logger.info("hook veto on %s: %s", event.value, veto)
                payload = {**payload, "_vetoed": True, "_veto_reason": str(veto)}
                return payload
            except Exception as e:
                logger.warning("hook error on %s: %s", event.value, e)
        return payload

    def load_from_file(self, path: Path) -> int:
        """Optional: load declarative hooks from JSON.

        File format::

            {
              "pre_classify": [
                {"type": "deny_keyword", "kw": "machine_learning_secret"}
              ]
            }
        """
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("hooks json load failed: %s", e)
            return 0
        loaded = 0
        for ev_name, configs in data.items():
            try:
                event = HookEvent(ev_name)
            except ValueError:
                logger.warning("unknown hook event %s", ev_name)
                continue
            for cfg in configs:
                fn = _make_declarative_hook(cfg)
                if fn:
                    self.register(event, fn)
                    loaded += 1
        return loaded


# ── Declarative hook factories ──


def _make_declarative_hook(cfg: Dict[str, Any]) -> Optional[HookFn]:
    kind = cfg.get("type")
    if kind == "deny_keyword":
        kw = (cfg.get("kw") or "").lower()
        if not kw:
            return None

        def _hook(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            text = (payload.get("content") or "").lower()
            if kw in text:
                raise HookVeto(f"contains denied keyword: {kw}")
            return None
        _hook.__name__ = f"deny_keyword_{kw}"
        return _hook
    if kind == "force_level":
        target_kw = (cfg.get("kw") or "").lower()
        level = cfg.get("level", "P0")

        def _hook(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            text = (payload.get("content") or "").lower()
            if target_kw and target_kw in text:
                return {"forced_level": level, "force_reason": f"hook:{target_kw}"}
            return None
        _hook.__name__ = f"force_level_{target_kw}"
        return _hook
    return None


_default: Optional[HookSystem] = None


def default_hooks() -> HookSystem:
    global _default
    if _default is None:
        _default = HookSystem()
    return _default
