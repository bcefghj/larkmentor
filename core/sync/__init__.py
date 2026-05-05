"""Multi-end synchronisation layer for Agent-Pilot v2.

Implements Scenario E (multi-end consistency). Three concerns:

1. **Agent state broadcast** – every ExecutionEvent from the
   orchestrator is fanned out to every connected client. This is a
   lightweight pub/sub WebSocket hub with optional Redis backend.
2. **Collaborative CRDT** – for the Doc / Canvas bodies themselves we
   persist a ``y-py`` ``YDoc`` per plan and accept y-websocket protocol
   messages. Offline merges come for free because Yjs handles them.
3. **Offline merge engine** – conflict detection / resolution with
   bounded offline queue, automatic reconciliation, and audit trail.
4. **Health monitoring** – per-room latency percentiles, connection
   stability, queue depth, and optional Prometheus export.

If ``y-py`` is not installed the sync layer still boots in
"broadcast-only" mode (plain JSON pub/sub), which is enough for the
first demo week.

If ``redis`` is not installed the hub runs in pure in-memory mode.
"""

from .crdt_hub import (
    CrdtHub,
    attach_orchestrator,
    broadcast_event,
    broadcast_state,
    default_hub,
)
from .health import SyncHealthMonitor, default_monitor
from .offline_merge import (
    ConflictStrategy,
    OfflineMergeEngine,
    default_engine,
    reconcile,
    record_offline_update,
)

__all__ = [
    "CrdtHub",
    "default_hub",
    "broadcast_state",
    "broadcast_event",
    "attach_orchestrator",
    "OfflineMergeEngine",
    "ConflictStrategy",
    "default_engine",
    "record_offline_update",
    "reconcile",
    "SyncHealthMonitor",
    "default_monitor",
]
