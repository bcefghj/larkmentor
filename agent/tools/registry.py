"""Unified tool registry · @tool decorator + registry lookup."""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("agent.tools.registry")


@dataclass
class ToolMeta:
    name: str
    description: str
    fn: Callable
    permission: str = "default"  # "readonly" / "write" / "sensitive"
    team: str = "default"  # which named agent can use it
    signature: str = ""


_REGISTRY: Dict[str, ToolMeta] = {}


def tool(
    *, name: str,
    description: str = "",
    permission: str = "default",
    team: str = "default",
) -> Callable:
    def _wrap(fn: Callable) -> Callable:
        sig = str(inspect.signature(fn))
        _REGISTRY[name] = ToolMeta(
            name=name,
            description=description or (fn.__doc__ or "").strip()[:200],
            fn=fn,
            permission=permission,
            team=team,
            signature=sig,
        )
        fn._tool_name = name  # type: ignore
        return fn
    return _wrap


def get_registry() -> Dict[str, ToolMeta]:
    return dict(_REGISTRY)


def call_tool(name: str, **kwargs) -> Any:
    meta = _REGISTRY.get(name)
    if not meta:
        raise KeyError(f"tool not registered: {name}")
    return meta.fn(**kwargs)


def register_builtin_tools() -> None:
    """Called once at import time to ensure all tools are visible."""
    logger.info("tool registry: %d tools registered", len(_REGISTRY))


def tools_for_llm_prompt(team: str = "default") -> str:
    """Generate tool listing for LLM context."""
    lines = ["=== AVAILABLE TOOLS ==="]
    for meta in _REGISTRY.values():
        if team != "default" and meta.team not in {team, "default", "any"}:
            continue
        lines.append(f"- {meta.name}{meta.signature}: {meta.description[:100]}")
    return "\n".join(lines)
