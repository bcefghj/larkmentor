"""Hooks · 6 生命周期事件（对齐 Claude Code）

6 事件：SessionStart / UserPromptSubmit / PreToolUse / PostToolUse / PreCompact / Stop

Hook 函数：`fn(event: str, payload: dict) -> Optional[dict]`
- 返回 dict → merge 进 payload（新 dict 胜）
- 返回 {"_veto": True, "_reason": "..."} → 阻断事件链
- 返回 None → no-op

支持 .larkmentor/hooks.json 声明式注册。
"""

from __future__ import annotations

import enum
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("agent.hooks")


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
        self._seed_defaults()
        self._load_json_hooks()

    # ── Register / clear ──

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

    # ── Fire ──

    def fire(self, event: HookEvent, payload: Dict[str, Any]) -> HookOutcome:
        merged = dict(payload)
        tripped: List[str] = []
        with self._lock:
            fns = list(self._hooks.get(event.value, []))
        for fn in fns:
            try:
                result = fn(event.value, merged)
            except Exception as e:
                logger.exception("hook %s raised: %s", getattr(fn, "__name__", "?"), e)
                continue
            if result is None:
                continue
            if isinstance(result, dict):
                if result.get("_veto"):
                    tripped.append(getattr(fn, "__name__", "veto"))
                    return HookOutcome(
                        payload=merged, vetoed=True,
                        veto_reason=result.get("_reason", ""),
                        tripped=tripped,
                    )
                merged.update(result)
                tripped.append(getattr(fn, "__name__", "update"))
        self._record(event.value, merged, tripped)
        return HookOutcome(payload=merged, tripped=tripped)

    def _record(self, event: str, payload: Dict[str, Any], tripped: List[str]) -> None:
        with self._lock:
            self._history.append({
                "event": event,
                "tripped": tripped,
                "keys": list(payload.keys()),
            })
            if len(self._history) > self._history_limit:
                self._history = self._history[-self._history_limit:]

    # ── Default hooks (6 events) ──

    def _seed_defaults(self) -> None:
        """Built-in defaults, can be overridden."""

        def _audit_pre(event: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """PreToolUse: append to audit log."""
            try:
                from core.observability import audit as _audit
                _audit("tool.call.pre", tool=payload.get("tool", "?"),
                       user=payload.get("user_open_id", ""),
                       plan_id=payload.get("plan_id", ""))
            except Exception:
                pass
            return None

        def _audit_post(event: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """PostToolUse: audit completion + progress card update."""
            try:
                from core.observability import audit as _audit
                _audit("tool.call.post", tool=payload.get("tool", "?"),
                       user=payload.get("user_open_id", ""),
                       plan_id=payload.get("plan_id", ""),
                       ok=payload.get("ok", True))
            except Exception:
                pass
            return None

        def _session_start(event: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """Inject LARKMENTOR.md chain."""
            try:
                from .memory import default_memory
                mem = default_memory()
                system_prompt = mem.build_system_prompt()
                if system_prompt:
                    return {"system_prompt": system_prompt}
            except Exception:
                pass
            return None

        def _pre_compact(event: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """Backup transcript before compaction."""
            try:
                home = Path(os.getenv("LARKMENTOR_HOME", str(Path.home() / ".larkmentor")))
                sessions_dir = home / "sessions"
                sessions_dir.mkdir(parents=True, exist_ok=True)
                import time as _t
                fname = sessions_dir / f"session_{int(_t.time())}.json"
                fname.write_text(
                    json.dumps(payload.get("messages", []), ensure_ascii=False)[:1_000_000],
                    encoding="utf-8"
                )
            except Exception:
                pass
            return None

        self.register(HookEvent.SESSION_START, _session_start, name="session_start.inject_larkmentor_md")
        self.register(HookEvent.PRE_TOOL_USE, _audit_pre, name="pre_tool_use.audit")
        self.register(HookEvent.POST_TOOL_USE, _audit_post, name="post_tool_use.audit")
        self.register(HookEvent.PRE_COMPACT, _pre_compact, name="pre_compact.backup")

    def _load_json_hooks(self) -> None:
        """Load declarative hooks from .larkmentor/hooks.json (best-effort)."""
        candidates = [
            Path.cwd() / ".larkmentor" / "hooks.json",
            Path.home() / ".larkmentor" / "hooks.json",
        ]
        for p in candidates:
            if not p.exists():
                continue
            try:
                data = json.loads(p.read_text())
                for entry in data.get("hooks", []):
                    event_name = entry.get("event")
                    cmd = entry.get("command")
                    if not event_name or not cmd:
                        continue
                    event = HookEvent(event_name)

                    def _shell_hook(event: str, payload: Dict[str, Any], _cmd: str = cmd) -> Optional[Dict[str, Any]]:
                        try:
                            import subprocess
                            env = os.environ.copy()
                            env["LARKMENTOR_HOOK_EVENT"] = event
                            env["LARKMENTOR_HOOK_PAYLOAD"] = json.dumps(payload, ensure_ascii=False)[:4000]
                            result = subprocess.run(_cmd, shell=True, capture_output=True, timeout=10, env=env, text=True)
                            if result.returncode == 0 and result.stdout.strip():
                                try:
                                    return json.loads(result.stdout)
                                except Exception:
                                    return None
                        except Exception:
                            pass
                        return None

                    self.register(event, _shell_hook, name=f"json:{event_name}:{cmd[:40]}")
                logger.info("loaded %d declarative hooks from %s", len(data.get("hooks", [])), p)
                return
            except Exception as e:
                logger.warning("hooks.json load failed %s: %s", p, e)


_singleton: Optional[HookRegistry] = None


def default_hook_registry() -> HookRegistry:
    global _singleton
    if _singleton is None:
        _singleton = HookRegistry()
    return _singleton
