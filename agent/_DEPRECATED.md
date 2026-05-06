# DEPRECATED

This `agent/` directory contains the early-stage (v1-v8) Agent implementation.
It is **no longer used** in the v13 architecture.

The active code path is:
- `bot/event_handler.py` → `bot/handlers/pilot.py`
- → `core/agent_pilot/service.py` → `agent_pilot/runtime/planner.py`
- → `agent_pilot/tools/{doc,slide,canvas}.py`

This directory is kept for reference only and will be removed after the competition.
