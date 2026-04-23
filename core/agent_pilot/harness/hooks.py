"""Lifecycle hook registry (6 events) inspired by Claude Code hooks.

Events
------
SessionStart        – when an agent session begins (inject LARKMENTOR.md)
UserPromptSubmit    – when the user sends a new intent (pre-planning)
PreToolUse          – before every tool dispatch (audit log / permission re-check / input rewrite)
PostToolUse         – after tool result is available (auto-format / progress card update)
PreCompact          – before ContextManager triggers a compaction (transcript backup)
Stop                – when orchestrator decides to finish (verify completeness)

Each hook is a callable:

    fn(event: str, payload: dict) -> Optional[dict]

Return a dict to *merge* into the payload (the new dict wins).
Return ``{"_veto": True, "_reason": ..., "_error": ...}`` to block the event chain.
Return ``None`` for no-op.

Hooks can also be registered declaratively via JSON in ``.larkmentor/hooks.json``.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("pilot.harness.hooks")


class HookEvent(str, enum.Enum):
    SESSION_START = "session_start"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    PRE_COMPACT = "pre_compact"
    STOP = "stop"


HookFn = Callable[[str, Dict[str, Any]], Optional[Dict[str, Any]]]


@dataclass
class HookOutcome:
    payload: Dict[str, Any]
    vetoed: bool = False
    veto_reason: str = ""
    tripped: List[str] = field(default_factory=list)


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: Dict[str, List[HookFn]] = {e.value: [] for e in HookEvent}
        self._lock = threading.RLock()
        self._history: List[Dict[str, Any]] = []
        self._history_limit = 200

    def register(self, event: HookEvent, fn: HookFn, *, name: str = "") -> None:
        with self._lock:
            self._hooks.setdefault(event.value, []).append(fn)
            logger.info("hook registered: %s ← %s", event.value, name or getattr(fn, "__name__", repr(fn)))

    def clear(self, event: Optional[HookEvent] = None) -> None:
        with self._lock:
            if event is None:
                for k in self._hooks:
                    self._hooks[k] = []
            else:
                self._hooks[event.value] = []

    def fire(self, event: HookEvent, payload: Dict[str, Any]) -> HookOutcome:
        """Run all hooks; returns merged payload + veto flag."""
        tripped: List[str] = []
        merged = dict(payload)
        with self._lock:
            hooks = list(self._hooks.get(event.value, []))
        for fn in hooks:
            try:
                out = fn(event.value, merged)
            except Exception as exc:
                logger.warning("hook raised on %s: %s", event.value, exc)
                continue
            if not isinstance(out, dict):
                continue
            tripped.append(getattr(fn, "__name__", "anon"))
            if out.get("_veto"):
                reason = out.get("_reason", "hook vetoed")
                self._remember(event, payload, merged, vetoed=True, reason=reason)
                return HookOutcome(payload=merged, vetoed=True, veto_reason=reason, tripped=tripped)
            merged = {**merged, **{k: v for k, v in out.items() if not k.startswith("_")}}
        self._remember(event, payload, merged, vetoed=False, reason="")
        return HookOutcome(payload=merged, tripped=tripped)

    def load_declarative(self, path: str) -> int:
        """Load declarative hooks from ``path``. JSON schema::

            {
              "pre_tool_use": [
                {"type": "deny_tool", "tool": "drive.delete", "reason": "too risky"},
                {"type": "log_audit"}
              ],
              "session_start": [
                {"type": "inject_memory", "file": "LARKMENTOR.md"}
              ]
            }
        """
        if not os.path.exists(path):
            return 0
        try:
            data = json.loads(open(path, "r", encoding="utf-8").read())
        except Exception as exc:
            logger.warning("declarative hooks load failed: %s", exc)
            return 0
        count = 0
        for ev_name, configs in (data or {}).items():
            try:
                event = HookEvent(ev_name)
            except ValueError:
                logger.warning("unknown hook event %s", ev_name)
                continue
            for cfg in configs or []:
                fn = _declarative_hook(cfg)
                if fn:
                    self.register(event, fn, name=cfg.get("type", "declarative"))
                    count += 1
        return count

    def _remember(self, event: HookEvent, before: Dict[str, Any], after: Dict[str, Any], *,
                  vetoed: bool, reason: str) -> None:
        entry = {
            "ts": int(time.time() * 1000),
            "event": event.value,
            "before_keys": sorted(list(before.keys()))[:16],
            "after_keys": sorted(list(after.keys()))[:16],
            "vetoed": vetoed,
            "reason": reason,
        }
        with self._lock:
            self._history.append(entry)
            if len(self._history) > self._history_limit:
                self._history = self._history[-self._history_limit:]

    def history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._history)


def _declarative_hook(cfg: Dict[str, Any]) -> Optional[HookFn]:
    kind = cfg.get("type", "")
    if kind == "deny_tool":
        tool = cfg.get("tool", "")
        reason = cfg.get("reason", f"denied: {tool}")

        def _fn(ev, payload):
            if payload.get("tool") == tool:
                return {"_veto": True, "_reason": reason}
            return None
        _fn.__name__ = f"deny_tool_{tool}"
        return _fn

    if kind == "log_audit":
        audit_path = cfg.get("path") or os.path.expanduser("~/.larkmentor/audit.jsonl")

        def _fn(ev, payload):
            try:
                os.makedirs(os.path.dirname(audit_path), exist_ok=True)
                with open(audit_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "ts": int(time.time() * 1000),
                        "event": ev,
                        "tool": payload.get("tool"),
                        "plan_id": payload.get("plan_id"),
                        "user": payload.get("user_open_id"),
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
            return None
        _fn.__name__ = "log_audit"
        return _fn

    if kind == "inject_memory":
        fpath = cfg.get("file", "LARKMENTOR.md")

        def _fn(ev, payload):
            try:
                if os.path.exists(fpath):
                    content = open(fpath, "r", encoding="utf-8").read()
                    return {"memory_injected": content[:8000]}
            except Exception:
                pass
            return None
        _fn.__name__ = f"inject_memory_{os.path.basename(fpath)}"
        return _fn

    if kind == "rewrite_arg":
        tool = cfg.get("tool", "")
        arg = cfg.get("arg", "")
        value = cfg.get("value", "")

        def _fn(ev, payload):
            if payload.get("tool") != tool:
                return None
            args = dict(payload.get("args") or {})
            args[arg] = value
            return {"args": args}
        _fn.__name__ = f"rewrite_{tool}_{arg}"
        return _fn

    logger.warning("unknown declarative hook type=%s", kind)
    return None


_default: Optional[HookRegistry] = None
_default_lock = threading.Lock()


def default_hook_registry() -> HookRegistry:
    global _default
    with _default_lock:
        if _default is None:
            _default = HookRegistry()
            _seed_defaults(_default)
        return _default


def _seed_defaults(reg: HookRegistry) -> None:
    """Register built-in hooks: audit log + sensitive tool gate + session memory inject."""
    audit_path = os.path.expanduser("~/.larkmentor/audit.jsonl")

    def _audit(ev, payload):
        try:
            os.makedirs(os.path.dirname(audit_path), exist_ok=True)
            with open(audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": int(time.time() * 1000),
                    "event": ev,
                    "tool": payload.get("tool"),
                    "plan_id": payload.get("plan_id"),
                    "user": payload.get("user_open_id"),
                    "args_keys": sorted(list((payload.get("args") or {}).keys()))[:16],
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return None
    _audit.__name__ = "audit_log"
    reg.register(HookEvent.PRE_TOOL_USE, _audit, name="audit_log")

    SENSITIVE = {"drive.delete", "bitable.clear", "im.batch_send", "calendar.cancel"}

    def _sensitive_gate(ev, payload):
        tool = payload.get("tool", "")
        mode = payload.get("permission_mode", "default")
        if tool in SENSITIVE and mode not in ("auto", "dontAsk", "bypassPermissions"):
            return {"_veto": True, "_reason": f"sensitive tool {tool} blocked in mode {mode}"}
        return None
    _sensitive_gate.__name__ = "sensitive_gate"
    reg.register(HookEvent.PRE_TOOL_USE, _sensitive_gate, name="sensitive_gate")

    def _session_inject(ev, payload):
        root = payload.get("project_root") or os.getcwd()
        md_path = os.path.join(root, "LARKMENTOR.md")
        if os.path.exists(md_path):
            try:
                content = open(md_path, "r", encoding="utf-8").read()
                return {"memory_injected": content[:8000]}
            except Exception:
                pass
        return None
    _session_inject.__name__ = "inject_larkmentor_md"
    reg.register(HookEvent.SESSION_START, _session_inject, name="inject_larkmentor_md")
