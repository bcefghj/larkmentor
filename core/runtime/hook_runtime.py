"""HookRuntime · Lifecycle Hook 系统的 facade (Claude Code 支柱 2)

LarkMentor 已经有 ``core/security/hook_system.py`` 实现 9 个 lifecycle
events（PRE_CLASSIFY / POST_CLASSIFY / PRE_REPLY / ... / PRE_LLM_CALL /
POST_LLM_CALL / PRE_TOOL_CALL / POST_TOOL_CALL）。

本模块提供一个 thin facade：
- 统一对外接口（domain 代码不直接 import security/hook_system）
- 暴露给 runtime/tool_registry 在 invoke 前后自动 fire 钩子
- 暴露给 SkillLoader 在加载/卸载 Skill 时 fire 钩子

设计原则（ARCHITECTURE.md §2 原则 1）：所有 domain 代码通过 runtime
访问 hooks，而不是直接 import security 包。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("larkmentor.runtime.hook_runtime")


class HookRuntime:
    """Facade over ``core.security.hook_system.HookSystem``"""

    def __init__(self) -> None:
        from core.security.hook_system import default_hooks
        self._hs = default_hooks()

    # ── Lifecycle events used by ToolRegistry / Domain code ──

    def fire_pre_classify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from core.security.hook_system import HookEvent
        return self._hs.fire(HookEvent.PRE_CLASSIFY, payload)

    def fire_post_classify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from core.security.hook_system import HookEvent
        return self._hs.fire(HookEvent.POST_CLASSIFY, payload)

    def fire_pre_reply(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from core.security.hook_system import HookEvent
        return self._hs.fire(HookEvent.PRE_REPLY, payload)

    def fire_post_reply(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from core.security.hook_system import HookEvent
        return self._hs.fire(HookEvent.POST_REPLY, payload)

    def fire_pre_tool_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from core.security.hook_system import HookEvent
        return self._hs.fire(HookEvent.PRE_TOOL_CALL, payload)

    def fire_post_tool_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from core.security.hook_system import HookEvent
        return self._hs.fire(HookEvent.POST_TOOL_CALL, payload)

    def fire_pre_llm_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from core.security.hook_system import HookEvent
        return self._hs.fire(HookEvent.PRE_LLM_CALL, payload)

    def fire_post_llm_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from core.security.hook_system import HookEvent
        return self._hs.fire(HookEvent.POST_LLM_CALL, payload)

    # ── Registration ─────────────────────────────────────────

    def register(self, event_name: str, fn: Callable) -> None:
        """Register a hook by event name (one of HookEvent members)."""
        from core.security.hook_system import HookEvent
        try:
            ev = HookEvent(event_name)
        except ValueError:
            logger.warning("unknown hook event %s", event_name)
            return
        self._hs.register(ev, fn)

    def load_from_file(self, path: str) -> int:
        from pathlib import Path
        return self._hs.load_from_file(Path(path))


_default: Optional[HookRuntime] = None


def default_hook_runtime() -> HookRuntime:
    global _default
    if _default is None:
        _default = HookRuntime()
    return _default
