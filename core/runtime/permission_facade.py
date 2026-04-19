"""PermissionFacade · 5 级权限系统的 facade (Claude Code 支柱 4)

LarkMentor 已经有 ``core/security/permission_manager.py`` 实现 5 级权限
（READ_ONLY / SAFE_REPLY / DRAFT_ACTION / SEND_ACTION / YOLO）+ 25+ 工具
默认级别表 + deny-by-default。

本模块提供 thin facade：
- runtime/tool_registry.py 在 invoke 前调 ``check`` 做检查
- domain 代码不直接 import security/permission_manager
- 测试时可以 mock 此 facade

设计原则（ARCHITECTURE.md §2 原则 1）：所有 domain 调用通过 facade
访问权限系统。
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

logger = logging.getLogger("larkmentor.runtime.permission_facade")


class PermissionFacade:
    """Facade over ``core.security.permission_manager.PermissionManager``"""

    def __init__(self) -> None:
        from core.security.permission_manager import default_manager
        self._pm = default_manager()

    def check(self, tool: str, user_open_id: str) -> Tuple[bool, str]:
        """Returns (allowed, reason)"""
        try:
            decision = self._pm.check(tool=tool, user_open_id=user_open_id or "anonymous")
            return decision.allowed, decision.reason
        except Exception as e:
            logger.warning("permission_facade.check error: %s", e)
            return False, f"facade_error:{e}"

    def set_user_level(self, user_open_id: str, level_name: str) -> bool:
        """Set per-user permission level by name."""
        from core.security.permission_manager import PermissionLevel
        try:
            level = PermissionLevel[level_name]
        except KeyError:
            return False
        self._pm.set_user_level(user_open_id, level)
        return True

    def get_user_level(self, user_open_id: str) -> str:
        return self._pm.get_user_level(user_open_id).name


_default: Optional[PermissionFacade] = None


def default_facade() -> PermissionFacade:
    global _default
    if _default is None:
        _default = PermissionFacade()
    return _default
