"""Agent-Pilot: LarkMentor v2 multi-end Agent orchestration core.

This package implements the six competition scenarios (A-F):
    A. Intent entry (IM text/voice)
    B. Task understanding & planning (LLM Planner)
    C. Document / whiteboard generation
    D. Slide / canvas generation & rehearsal
    E. Multi-end consistency
    F. Summary & delivery (archive, share link)

Key modules:
    planner       – Doubao-driven DAG planner (Scenario B).
    orchestrator  – Executes the DAG, broadcasts progress via CRDT hub.
    scenarios     – Registry for A-F scenario modules.
    tools/        – Callable tools that the planner can route to.
"""

from .planner import PilotPlanner, Plan, PlanStep
from .orchestrator import PilotOrchestrator, ExecutionEvent
from .scenarios import ScenarioRegistry, Scenario

__all__ = [
    "PilotPlanner",
    "Plan",
    "PlanStep",
    "PilotOrchestrator",
    "ExecutionEvent",
    "ScenarioRegistry",
    "Scenario",
]
