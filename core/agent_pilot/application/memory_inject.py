"""6-tier Memory 注入桥 (P15) · 把 ``core.flow_memory.flow_memory_md`` 接到
Pilot 主流程的 system prompt.

PRD §7.5 + ARCHITECTURE §1 §2 原则 5 的工程兑现：
- Enterprise / Workspace / Department / Group / User / Session 6 级 markdown
- 每次 LLM 调用前自动从低层向高层覆盖合并
- 通过 ``ContextService.memory_resolver`` 注入
- 通过 ``IntentDetector.llm_caller`` 包装在 LLM judge 调用前

设计：
- 不修改 ``core/flow_memory/flow_memory_md.py``（保留 v6 实现）
- 仅做 facade adapter
- 单例 ``default_memory_injector()``，main.py 启动时绑定
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("pilot.application.memory_inject")


def make_memory_resolver_adapter() -> Callable[..., str]:
    """返回 ``ContextService.memory_resolver`` 兼容签名的函数.

    把 ContextBuildOptions 的 (tenant, workspace, department, group, user, session)
    参数映射到 flow_memory_md.resolve_memory_md 的命名参数。
    """
    try:
        from core.flow_memory.flow_memory_md import resolve_memory_md
    except Exception as e:
        logger.warning("flow_memory_md not available: %s", e)
        return lambda **_kw: ""

    def _adapter(*, tenant: str = "default",
                 workspace: str = "default",
                 department: str = "",
                 group: str = "",
                 user: str = "",
                 session: str = "") -> str:
        try:
            return resolve_memory_md(
                enterprise_id=tenant or "default",
                workspace_id=workspace or "default",
                department_id=department or None,
                group_id=group or None,
                user_open_id=user or None,
                session_id=session or None,
            ) or ""
        except Exception as e:
            logger.debug("resolve_memory_md failed: %s", e)
            return ""

    return _adapter


def wrap_llm_with_memory(llm_caller: Callable[[str], str], *,
                          tenant: str = "default", workspace: str = "default",
                          department: str = "", group: str = "",
                          user: str = "", session: str = "") -> Callable[[str], str]:
    """对 ``IntentDetector.llm_caller`` 做包装：在 user prompt 前注入 6 级 memory.

    包装后的函数签名仍然是 ``(im_text) -> raw_response_str``。
    """
    resolver = make_memory_resolver_adapter()

    def _wrapped(im_text: str) -> str:
        md = resolver(tenant=tenant, workspace=workspace,
                       department=department, group=group,
                       user=user, session=session)
        if md:
            prefixed = f"<memory_context>\n{md[:3000]}\n</memory_context>\n\n{im_text}"
        else:
            prefixed = im_text
        return llm_caller(prefixed)

    return _wrapped


def attach_memory_to_default_services() -> None:
    """启动时调一次：把 6 级 memory resolver 绑定到 default_context_service()."""
    try:
        from .context_service import default_context_service
        adapter = make_memory_resolver_adapter()
        ctx = default_context_service()
        ctx.memory_resolver = adapter
        logger.info("6-tier memory resolver attached to default_context_service")
    except Exception as e:
        logger.warning("attach memory to default_context_service failed: %s", e)


__all__ = [
    "make_memory_resolver_adapter",
    "wrap_llm_with_memory",
    "attach_memory_to_default_services",
]
