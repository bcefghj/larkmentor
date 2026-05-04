"""Agent-Pilot: LarkMentor v2 multi-end Agent orchestration core.

This package implements the six competition scenarios (A-F):
    A. Intent entry (IM text/voice)
    B. Task understanding & planning (LLM Planner)
    C. Document / whiteboard generation
    D. Slide / canvas generation & rehearsal
    E. Multi-end consistency
    F. Summary & delivery (archive, share link)

Architecture (unified as of v7.1):
    - ConversationOrchestrator (harness/) is the SINGLE execution engine
    - PilotOrchestrator (orchestrator.py) is retained for backwards compat only
    - OrchestratorService (application/) adapts Task state machine on top
    - service.py is the public facade (launch / get_plan / list_plans)

Key modules:
    planner       – Doubao-driven DAG planner (Scenario B).
    harness/      – Production agent loop (gather → plan → dispatch → verify → reflect).
    orchestrator  – Legacy DAG executor (backwards compat, delegates to harness).
    scenarios     – Registry for A-F scenario modules.
    tools/        – Callable tools that the planner can route to.
"""

from .planner import PilotPlanner, Plan, PlanStep
from .orchestrator import PilotOrchestrator, ExecutionEvent
from .scenarios import ScenarioRegistry, Scenario
from .service import get_orchestrator, launch, get_plan, list_plans

__all__ = [
    "PilotPlanner",
    "Plan",
    "PlanStep",
    "PilotOrchestrator",
    "ExecutionEvent",
    "ScenarioRegistry",
    "Scenario",
    "get_orchestrator",
    "launch",
    "get_plan",
    "list_plans",
]
