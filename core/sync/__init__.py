"""Multi-end synchronisation layer for LarkMentor v2 Agent-Pilot.

Implements Scenario E (multi-end consistency). Two concerns:

1. **Agent state broadcast** – every ExecutionEvent from the
   orchestrator is fanned out to every connected client. This is a
   lightweight pub/sub WebSocket hub.
2. **Collaborative CRDT** – for the Doc / Canvas bodies themselves we
   persist a ``y-py`` ``YDoc`` per plan and accept y-websocket protocol
   messages. Offline merges come for free because Yjs handles them.

If ``y-py`` is not installed the sync layer still boots in
"broadcast-only" mode (plain JSON pub/sub), which is enough for the
first demo week.
"""

from .crdt_hub import (
    CrdtHub,
    default_hub,
    broadcast_state,
    broadcast_event,
    attach_orchestrator,
)

__all__ = [
    "CrdtHub",
    "default_hub",
    "broadcast_state",
    "broadcast_event",
    "attach_orchestrator",
]
