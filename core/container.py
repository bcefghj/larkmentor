"""Lightweight DI container for Agent-Pilot.

Replaces scattered global ``_singleton`` patterns with a central registry.
Supports lazy initialization, scoped lifetimes, and test-time overrides.

Usage:
    from core.container import get_container, resolve

    # At startup
    register_defaults()

    # In application code
    orchestrator = resolve("orchestrator")

    # In tests
    get_container().override("memory", MockMemory())
"""
from __future__ import annotations

import logging
import threading
from enum import Enum
from typing import Any, Callable, Dict, Optional, Type, TypeVar, overload

logger = logging.getLogger("agent_pilot.container")

T = TypeVar("T")


class Lifetime(str, Enum):
    SINGLETON = "singleton"
    TRANSIENT = "transient"


class Container:
    """Process-wide service locator with lazy init, lifetimes, and test overrides."""

    def __init__(self) -> None:
        self._factories: Dict[str, Callable[[], Any]] = {}
        self._lifetimes: Dict[str, Lifetime] = {}
        self._instances: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def register(
        self,
        key: str,
        factory: Callable[[], Any],
        *,
        lifetime: Lifetime = Lifetime.SINGLETON,
    ) -> None:
        with self._lock:
            self._factories[key] = factory
            self._lifetimes[key] = lifetime
            if lifetime == Lifetime.TRANSIENT:
                self._instances.pop(key, None)
            else:
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
            lifetime = self._lifetimes.get(key, Lifetime.SINGLETON)
            if lifetime == Lifetime.SINGLETON:
                self._instances[key] = instance
            return instance

    def reset(self) -> None:
        """Clear all instances (for testing). Factories remain."""
        with self._lock:
            self._instances.clear()

    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._factories or key in self._instances

    def snapshot(self) -> Dict[str, Any]:
        """Return a diagnostic snapshot of registered services."""
        with self._lock:
            return {
                "registered": list(self._factories.keys()),
                "instantiated": list(self._instances.keys()),
                "total_factories": len(self._factories),
                "total_instances": len(self._instances),
            }


_container = Container()


def get_container() -> Container:
    return _container


def resolve(key: str) -> Any:
    """Shortcut to resolve a service from the global container."""
    return _container.resolve(key)


def register_defaults() -> None:
    """Register default service factories. Called once at startup."""
    c = _container

    c.register("tool_registry", lambda: _make_tool_registry())
    c.register("orchestrator", lambda: _make_orchestrator())
    c.register("orchestrator_service", lambda: _make_orchestrator_service())
    c.register("intent_detector", lambda: _make_intent_detector())
    c.register("memory", lambda: _make_memory())
    c.register("permission_gate", lambda: _make_permission_gate())
    c.register("hook_registry", lambda: _make_hook_registry())
    c.register("prompt_cache", lambda: _make_prompt_cache())
    c.register("planner", lambda: _make_planner())
    c.register("crdt_hub", lambda: _make_crdt_hub())
    c.register("llm_provider_router", lambda: _make_llm_router())

    logger.info("DI container: %d default factories registered", len(c._factories))


# ── Factory functions ──


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
        prompt_cache=_container.resolve("prompt_cache"),
    )


def _make_orchestrator_service():
    from core.agent_pilot.application.orchestrator_service import (
        OrchestratorConfig,
        OrchestratorService,
    )

    return OrchestratorService(config=OrchestratorConfig())


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


def _make_prompt_cache():
    from core.agent_pilot.harness.prompt_cache import default_prompt_cache

    return default_prompt_cache()


def _make_planner():
    from core.agent_pilot.planner import PilotPlanner

    return PilotPlanner()


def _make_crdt_hub():
    from core.sync.crdt_hub import default_hub

    return default_hub()


def _make_llm_router():
    try:
        from agent.providers import default_providers
        return default_providers()
    except Exception:
        return None
