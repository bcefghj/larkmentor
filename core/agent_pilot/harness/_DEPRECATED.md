# DEPRECATED

This `harness/` directory contains the v7-v12 orchestration layer
(orchestrator_v2, context_cascade, streaming_executor, etc.).

In v13, the active orchestration path is:
- `core/agent_pilot/service.py` → `agent_pilot/runtime/planner.py` (DAG planner)
- → `agent_pilot/intel/multi_agent.py` (4-Agent pipeline)

The harness modules are retained as infrastructure (MCP client, memory, hooks)
but `orchestrator_v2.py` is no longer the primary execution path.
