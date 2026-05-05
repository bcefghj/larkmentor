"""Lightweight DI container for Agent-Pilot.

Replaces scattered global ``_singleton`` patterns with a central registry.
Supports lazy initialization and test-time overrides.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, Optional, TypeVar

logger = logging.getLogger("agent_pilot.container")

T = TypeVar("T")


class Container:
    """Process-wide service locator with lazy init and test overrides."""

    def __init__(self) -> None:
        self._factories: Dict[str, Callable[[], Any]] = {}
        self._instances: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def register(self, key: str, factory: Callable[[], Any]) -> None:
        with self._lock:
            self._factories[key] = factory
            self._instances.pop(key, None)

    def override(self, key: str, instance: Any) -> None:
        """For testing: inject a pre-built instance."""
        with self._lock:
            self._instances[key] = instance

    def resolve(self, key: str) -> Any:
        with self._lock:
            if key in self._instances:
                return self._instances[key]
            factory = self._factories.get(key)
            if factory is None:
                raise KeyError(f"No factory registered for '{key}'")
            instance = factory()
            self._instances[key] = instance
            return instance

    def reset(self) -> None:
        """Clear all instances (for testing)."""
        with self._lock:
            self._instances.clear()

    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._factories or key in self._instances


_container = Container()


def get_container() -> Container:
    return _container


def register_defaults() -> None:
    """Register default service factories. Called once at startup."""
    c = _container

    c.register("tool_registry", lambda: _make_tool_registry())
    c.register("orchestrator", lambda: _make_orchestrator())
    c.register("intent_detector", lambda: _make_intent_detector())
    c.register("memory", lambda: _make_memory())
    c.register("permission_gate", lambda: _make_permission_gate())
    c.register("hook_registry", lambda: _make_hook_registry())

    logger.info("DI container: default factories registered")


def _make_tool_registry():
    from core.agent_pilot.harness.tool_registry import ToolRegistry, _populate_default

    reg = ToolRegistry()
    _populate_default(reg)
    return reg


def _make_orchestrator():
    from core.agent_pilot.harness.orchestrator_v2 import ConversationOrchestrator

    return ConversationOrchestrator(
        tools=_container.resolve("tool_registry"),
        hooks=_container.resolve("hook_registry"),
        permissions=_container.resolve("permission_gate"),
        memory=_container.resolve("memory"),
    )


def _make_intent_detector():
    from core.agent_pilot.application.intent_detector import IntentDetector

    return IntentDetector()


def _make_memory():
    from core.agent_pilot.harness.memory import default_memory

    return default_memory()


def _make_permission_gate():
    from core.agent_pilot.harness.permissions import default_permission_gate

    return default_permission_gate()


def _make_hook_registry():
    from core.agent_pilot.harness.hooks import default_hook_registry

    return default_hook_registry()
