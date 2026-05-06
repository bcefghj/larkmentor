"""Agent-Pilot v13 – modular runtime package.

Public re-exports for the rest of the codebase. Old `core.agent_pilot.*`
imports keep working through `core/agent_pilot/__init__.py` thin shims.
"""

from __future__ import annotations

__version__ = "13.0.0"

# Eager exports of the most-used types so `from agent_pilot import Plan` works.
from agent_pilot.runtime.planner import Plan, PlanStep, plan_from_intent  # noqa: F401
from agent_pilot.llm.safe_json import safe_json_parse  # noqa: F401

__all__ = [
    "__version__",
    "Plan",
    "PlanStep",
    "plan_from_intent",
    "safe_json_parse",
]
