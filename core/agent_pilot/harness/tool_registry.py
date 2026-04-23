"""Tool registry with Claude Code-style `buildTool` factory.

Key properties
--------------
* Composition over inheritance: every tool is a ToolSpec record.
* Schema doubles as prompt: the JSON-schema description is the same
  string rendered to the LLM as part of the system prompt.
* Concurrency marker: `readonly` tools run in parallel under the
  StreamingToolExecutor; write-capable tools grab the exclusive lock.
* Permission annotation: declares the minimum mode required (see
  permissions.PermissionMode).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("pilot.harness.tool_registry")


ToolFn = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


@dataclass
class ToolSpec:
    """A single tool exposed to the Agent Loop.

    Attributes
    ----------
    name
        Fully-qualified identifier, e.g. ``doc.create`` or ``im.fetch_thread``.
    description
        Human-readable / LLM-readable description. Rendered into the system
        prompt verbatim (acts as Zod schema).
    parameters
        JSON-schema style dict, ``{"arg_name": {"type": "str", "desc": "..."}}``.
    fn
        The callable. Signature: ``fn(args, ctx) -> dict``. Raises on hard error.
    readonly
        If True, the tool may run concurrently with other readonly tools.
        False tools take the exclusive write lock (serialised).
    destructive
        If True, the PermissionGate treats it as requiring explicit ``allow``
        in default/plan modes. Examples: delete operations, batch-send.
    needs_permission
        Minimum permission mode: default | acceptEdits | auto | dontAsk |
        bypassPermissions. See permissions.PermissionMode.
    category
        Optional tag (``im``, ``doc``, ``canvas``, ``slide``, ``mcp``, etc.)
        used for stats / dashboard grouping.
    timeout_sec
        Hard cap. Tool is cancelled and marked failed if exceeded.
    tags
        Free-form labels for skill matching / analytics.
    """

    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    fn: Optional[ToolFn] = None
    readonly: bool = False
    destructive: bool = False
    needs_permission: str = "default"
    category: str = "generic"
    timeout_sec: int = 60
    tags: List[str] = field(default_factory=list)

    def render_prompt_schema(self) -> str:
        """Render a compact description used inside the system prompt."""
        args_lines = []
        for k, spec in (self.parameters or {}).items():
            t = spec.get("type", "any") if isinstance(spec, dict) else "any"
            d = spec.get("desc", "") if isinstance(spec, dict) else ""
            args_lines.append(f"  - {k} ({t}): {d}")
        args_block = "\n".join(args_lines) if args_lines else "  (no args)"
        flags = []
        if self.readonly:
            flags.append("readonly")
        if self.destructive:
            flags.append("destructive")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        return (
            f"- {self.name}{flag_str}: {self.description}\n"
            f"{args_block}"
        )


def build_tool(
    name: str,
    description: str,
    fn: ToolFn,
    *,
    parameters: Optional[Dict[str, Any]] = None,
    readonly: bool = False,
    destructive: bool = False,
    needs_permission: str = "default",
    category: str = "generic",
    timeout_sec: int = 60,
    tags: Optional[List[str]] = None,
) -> ToolSpec:
    """Factory (Claude Code style). Keep call-sites declarative."""
    return ToolSpec(
        name=name,
        description=description,
        parameters=parameters or {},
        fn=fn,
        readonly=readonly,
        destructive=destructive,
        needs_permission=needs_permission,
        category=category,
        timeout_sec=timeout_sec,
        tags=tags or [],
    )


class ToolRegistry:
    """Thread-safe registry. Supports dynamic add/remove and lookup by prefix."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}
        self._lock = threading.RLock()

    def register(self, spec: ToolSpec) -> None:
        with self._lock:
            if spec.name in self._tools:
                logger.info("tool re-registered: %s", spec.name)
            self._tools[spec.name] = spec

    def unregister(self, name: str) -> None:
        with self._lock:
            self._tools.pop(name, None)

    def get(self, name: str) -> Optional[ToolSpec]:
        with self._lock:
            return self._tools.get(name)

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._tools

    def names(self) -> List[str]:
        with self._lock:
            return sorted(self._tools.keys())

    def list(self) -> List[ToolSpec]:
        with self._lock:
            return list(self._tools.values())

    def by_category(self, category: str) -> List[ToolSpec]:
        with self._lock:
            return [t for t in self._tools.values() if t.category == category]

    def render_all_schemas(self) -> str:
        """For the planner system prompt."""
        with self._lock:
            return "\n".join(t.render_prompt_schema() for t in self._tools.values())

    def as_mapping(self) -> Dict[str, ToolFn]:
        """Legacy callable mapping (name -> fn). For backwards compat."""
        with self._lock:
            return {n: s.fn for n, s in self._tools.items() if s.fn is not None}


_default: Optional[ToolRegistry] = None
_default_lock = threading.Lock()


def default_registry() -> ToolRegistry:
    """Process-wide registry, lazy-initialised on first access."""
    global _default
    with _default_lock:
        if _default is None:
            _default = ToolRegistry()
            _populate_default(_default)
        return _default


def _populate_default(reg: ToolRegistry) -> None:
    """Seed with the built-in Agent-Pilot tools, wrapping existing callables."""
    try:
        from core.agent_pilot.tools import build_default_registry
    except Exception as e:
        logger.warning("cannot import existing tools: %s", e)
        return
    legacy = build_default_registry()

    _annotations = {
        "im.fetch_thread":   dict(readonly=True,  category="im",      desc="拉取指定 chat_id 最近 N 条 IM 消息。"),
        "doc.create":        dict(readonly=False, category="doc",     desc="创建飞书 Docx 文档。"),
        "doc.append":        dict(readonly=False, category="doc",     desc="往已创建的飞书 Docx 追加 markdown 块。"),
        "canvas.create":     dict(readonly=False, category="canvas",  desc="创建 tldraw 画布；best-effort 同步到飞书画板。"),
        "canvas.add_shape":  dict(readonly=False, category="canvas",  desc="在画布上插入形状 / 图片 / sticky / 表格。"),
        "slide.generate":    dict(readonly=False, category="slide",   desc="把大纲编译成 Slidev PPT（pptx + pdf）。"),
        "slide.rehearse":    dict(readonly=False, category="slide",   desc="为 PPT 逐页生成演讲稿。"),
        "voice.transcribe":  dict(readonly=True,  category="voice",   desc="ASR 语音转写（豆包 / 妙记 / Whisper）。"),
        "archive.bundle":    dict(readonly=False, category="archive", desc="打包产物并生成飞书分享链接。"),
        "mentor.clarify":    dict(readonly=True,  category="mentor",  desc="Agent 主动向用户发出澄清问题。"),
        "mentor.summarize":  dict(readonly=True,  category="mentor",  desc="对一段对话/上下文做结构化总结。"),
    }

    for name, fn in legacy.items():
        meta = _annotations.get(name, {})
        reg.register(build_tool(
            name=name,
            description=meta.get("desc", f"Tool: {name}"),
            fn=lambda args, ctx, _f=fn: _fn_shim(_f, args, ctx),
            parameters={},
            readonly=meta.get("readonly", False),
            destructive=False,
            needs_permission="default",
            category=meta.get("category", "generic"),
            timeout_sec=60,
        ))
    logger.info("default ToolRegistry populated with %d tools", len(reg.names()))


def _fn_shim(legacy_fn, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt legacy ``(step, ctx)`` tools to the new ``(args, ctx)`` signature."""
    class _FakeStep:
        def __init__(self, a):
            self.args = a
            self.step_id = ctx.get("step_id", "")
            self.tool = ctx.get("tool", "")
            self.description = ctx.get("description", "")

    step = _FakeStep(args)
    merged_ctx = {**ctx, "resolved_args": args}
    result = legacy_fn(step, merged_ctx)
    return result or {}
