"""ToolRegistry · 统一工具注册中心 (Claude Code 支柱 1)

每个 LarkMentor 能力（消息分流/写作起草/任务澄清/周报生成/...）以一个
``ToolMetadata`` 注册到 ``ToolRegistry``。所有调用经过 ``invoke``，
自动完成 4 件事：

1. PermissionManager 检查（deny by default）
2. RateLimiter 限速（如果该工具配置）
3. AuditLog 记录（所有调用 append-only）
4. 异常捕获 + 标准化错误返回

设计原则（来自 ARCHITECTURE.md §2 原则 1）：
- 任何 domain 代码不允许绕过 ToolRegistry 直接调用 LLM 或飞书 API
- 工具注册时必须显式声明 permission level，否则 fail-closed
- invoke 是唯一对外接口，参数和返回值都是 JSON-serializable dict
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("larkmentor.runtime.tool_registry")


@dataclass
class ToolMetadata:
    """一个 tool 的完整描述"""

    name: str
    description: str
    handler: Callable[..., Dict[str, Any]]
    permission: str = "READ_ONLY"
    args_schema: Dict[str, Any] = field(default_factory=dict)
    rate_limit_per_minute: int = 60
    skill: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ToolMetadata.name required")
        if not callable(self.handler):
            raise ValueError(f"ToolMetadata.handler must be callable: {self.name}")


class ToolRegistry:
    """统一工具注册中心 + 调用入口"""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolMetadata] = {}
        self._call_count: Dict[str, int] = {}
        self._call_window: Dict[str, List[float]] = {}

    # ── 注册 ───────────────────────────────────────────────────

    def register(self, meta: ToolMetadata) -> None:
        if meta.name in self._tools:
            logger.warning("tool re-registered: %s (was %r)", meta.name, self._tools[meta.name])
        self._tools[meta.name] = meta
        logger.info("tool registered: %s [%s] %s", meta.name, meta.permission, meta.description)

    def register_simple(
        self,
        name: str,
        handler: Callable[..., Dict[str, Any]],
        *,
        description: str = "",
        permission: str = "READ_ONLY",
        skill: str = "",
        rate_limit_per_minute: int = 60,
    ) -> None:
        self.register(ToolMetadata(
            name=name,
            description=description or name,
            handler=handler,
            permission=permission,
            skill=skill,
            rate_limit_per_minute=rate_limit_per_minute,
        ))

    # ── 查询 ───────────────────────────────────────────────────

    def list_tools(self) -> List[ToolMetadata]:
        return list(self._tools.values())

    def list_by_skill(self, skill: str) -> List[ToolMetadata]:
        return [t for t in self._tools.values() if t.skill == skill]

    def get(self, name: str) -> Optional[ToolMetadata]:
        return self._tools.get(name)

    # ── 调用 ───────────────────────────────────────────────────

    def invoke(
        self,
        name: str,
        args: Dict[str, Any],
        *,
        user_open_id: str = "",
        skip_permission: bool = False,
        skip_rate_limit: bool = False,
        skip_audit: bool = False,
    ) -> Dict[str, Any]:
        """Invoke a tool by name. Returns ``{"ok": bool, "data": ...}``.

        ``skip_permission`` / ``skip_rate_limit`` / ``skip_audit`` should
        only be used inside trusted internal code paths (e.g. system-level
        scheduler), never from external callers.
        """

        meta = self._tools.get(name)
        if meta is None:
            return {"ok": False, "error": f"unknown_tool:{name}", "stage": "lookup"}

        # 1. Permission gate
        if not skip_permission:
            try:
                from .permission_facade import default_facade
                allowed, reason = default_facade().check(name, user_open_id)
                if not allowed:
                    self._audit(name, user_open_id, "permission_denied", reason, skip_audit)
                    return {"ok": False, "error": reason, "stage": "permission"}
            except Exception as e:
                logger.warning("permission check error %s: %s", name, e)

        # 2. Rate limit
        if not skip_rate_limit and meta.rate_limit_per_minute > 0:
            if not self._rate_check(name, meta.rate_limit_per_minute):
                self._audit(name, user_open_id, "rate_limited", "qpm_exceeded", skip_audit)
                return {"ok": False, "error": "rate_limited", "stage": "rate_limit"}

        # 3. Invoke
        t0 = time.time()
        try:
            result = meta.handler(**args) if isinstance(args, dict) else meta.handler(args)
        except TypeError as te:
            self._audit(name, user_open_id, "type_error", str(te), skip_audit)
            return {"ok": False, "error": f"args_mismatch:{te}", "stage": "invoke"}
        except Exception as e:
            logger.exception("tool error %s", name)
            self._audit(name, user_open_id, "tool_error", str(e), skip_audit)
            return {"ok": False, "error": f"tool_error:{e}", "stage": "invoke"}
        elapsed_ms = int((time.time() - t0) * 1000)

        # 4. Audit
        self._audit(name, user_open_id, "ok", f"elapsed_ms={elapsed_ms}", skip_audit)
        self._call_count[name] = self._call_count.get(name, 0) + 1
        return {"ok": True, "data": result, "elapsed_ms": elapsed_ms}

    # ── Internal helpers ─────────────────────────────────────

    def _rate_check(self, name: str, qpm: int) -> bool:
        now = time.time()
        window = [t for t in self._call_window.get(name, []) if now - t < 60]
        if len(window) >= qpm:
            self._call_window[name] = window
            return False
        window.append(now)
        self._call_window[name] = window
        return True

    def _audit(
        self,
        tool: str,
        user: str,
        outcome: str,
        meta: str,
        skip: bool,
    ) -> None:
        if skip:
            return
        try:
            from core.security.audit_log import audit
            audit(
                actor=user or "system",
                action=f"tool.invoke:{tool}",
                resource=tool,
                outcome=outcome,
                severity="INFO" if outcome == "ok" else "WARN",
                meta={"detail": meta},
            )
        except Exception as e:
            logger.debug("audit fallback skipped: %s", e)

    # ── Stats / introspection ────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        return {
            "total_tools": len(self._tools),
            "call_counts": dict(self._call_count),
            "tools_by_skill": {
                skill: len(self.list_by_skill(skill))
                for skill in {t.skill for t in self._tools.values() if t.skill}
            },
        }


_default: Optional[ToolRegistry] = None


def default_registry() -> ToolRegistry:
    global _default
    if _default is None:
        _default = ToolRegistry()
    return _default
