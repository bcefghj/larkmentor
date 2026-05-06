"""工具注册表 — 把工具函数装配成 LLM 可见的 schema + 可调用的 dispatcher.

设计:
  - 每个工具有 name / description / input_schema (JSON Schema) / read_only / handler
  - 注册时声明 read_only：Runtime 据此决定 read 并行 / write 串行（Cognition 教训）
  - default_registry() 返回单例，全 V1 共享
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("pilot.capability.tools.registry")


ToolHandler = Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    read_only: bool = True
    handler: Optional[ToolHandler] = None
    requires_approval: bool = False  # destructive 工具需要 governance 二次确认
    namespace: str = "pilot"  # pilot | lark-cli | mcp

    def to_llm_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    # ── 注册 ──
    def register(
        self,
        name: str,
        *,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        read_only: bool = True,
        requires_approval: bool = False,
        namespace: str = "pilot",
    ) -> Callable[[ToolHandler], ToolHandler]:
        def deco(fn: ToolHandler) -> ToolHandler:
            spec = ToolSpec(
                name=name,
                description=description or (fn.__doc__ or "").strip()[:200],
                input_schema=input_schema or {"type": "object", "properties": {}},
                read_only=read_only,
                handler=fn,
                requires_approval=requires_approval,
                namespace=namespace,
            )
            self._tools[name] = spec
            logger.debug("tool registered: %s (read_only=%s, ns=%s)", name, read_only, namespace)
            return fn

        return deco

    # ── 查询 ──
    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def is_read_only(self, name: str) -> bool:
        spec = self._tools.get(name)
        return bool(spec and spec.read_only)

    def list_specs(self, namespace: str | None = None) -> list[ToolSpec]:
        if namespace is None:
            return list(self._tools.values())
        return [s for s in self._tools.values() if s.namespace == namespace]

    def to_llm_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        if names is None:
            return [s.to_llm_schema() for s in self._tools.values()]
        return [s.to_llm_schema() for n in names if (s := self._tools.get(n))]

    # ── 调度（被 Runtime 通过 ToolDispatcher Protocol 调用）──
    async def execute(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        spec = self._tools.get(tool_name)
        if spec is None or spec.handler is None:
            raise ValueError(f"未知工具: {tool_name}")

        handler = spec.handler
        # 兼容同步 / 异步 handler
        try:
            kwargs = {**tool_input, "_ctx": ctx} if _accepts_kw(handler, "_ctx") else dict(tool_input)
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**kwargs)
            else:
                # 在 thread pool 里跑同步函数，避免阻塞事件循环
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: handler(**kwargs))
        except TypeError as e:
            # 如果签名不接 kwargs，尝试 positional
            logger.debug("tool %s kwargs failed: %s — trying without _ctx", tool_name, e)
            kwargs2 = dict(tool_input)
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**kwargs2)
            else:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: handler(**kwargs2))

        if not isinstance(result, dict):
            return {"value": result, "ok": True}
        return result


def _accepts_kw(fn: Callable, kw: str) -> bool:
    try:
        sig = inspect.signature(fn)
        return kw in sig.parameters or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
    except (TypeError, ValueError):
        return False


# ── 全局单例 ──


_default: ToolRegistry | None = None


def default_registry() -> ToolRegistry:
    global _default
    if _default is None:
        _default = ToolRegistry()
        _register_builtin_tools(_default)
    return _default


def _register_builtin_tools(reg: ToolRegistry) -> None:
    """注册所有内置工具（懒导入避免循环依赖）."""
    from pilot.capability.tools import (
        archive,
        canvas,
        doc,
        im_fetch,
        mentor,
        slide,
        voice,
        web_media,
    )

    doc.register_to(reg)
    canvas.register_to(reg)
    slide.register_to(reg)
    archive.register_to(reg)
    voice.register_to(reg)
    im_fetch.register_to(reg)
    mentor.register_to(reg)
    web_media.register_to(reg)

    try:
        from pilot.capability.tools import lark_tools

        lark_tools.register_to(reg)
    except ImportError:
        logger.debug("lark_tools 模块尚未实现，跳过注册")
    except Exception as e:
        logger.warning("lark_tools 注册失败: %s", e)
