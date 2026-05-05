"""Offline merge strategy with conflict resolution for Agent-Pilot.

Yjs CRDTs already guarantee convergence, but this module provides a
higher-level policy layer:

* **Conflict detection** – detects overlapping edits from different
  clients on the same field/path.
* **Resolution strategies** – ``last-writer-wins`` (default), ``merge``
  (union of changes), or ``ask-user`` (queue for manual resolution).
* **Bounded offline queue** – at most ``MAX_PENDING`` (1000) updates per
  room; oldest entries are evicted when the limit is reached.
* **Automatic reconciliation** – on reconnect, pending updates are
  flushed in causal order and the result is broadcast to the room.
* **Audit trail** – every merge decision is logged to disk for
  post-mortem debugging and compliance.

Data is stored under ``data/pilot_offline/``.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger("pilot.sync.offline")

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "pilot_offline",
)

MAX_PENDING = 1000


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


# ── Conflict resolution strategies ──


class ConflictStrategy(str, enum.Enum):
    LAST_WRITER_WINS = "last_writer_wins"
    MERGE = "merge"
    ASK_USER = "ask_user"


@dataclass
class OfflineUpdate:
    """A single update recorded while a client was offline."""

    room: str
    client_id: str
    update_b64: str
    field_path: str = ""
    ts: float = 0.0
    resolved: bool = False
    resolution: str = ""

    def __post_init__(self):
        if self.ts == 0.0:
            self.ts = time.time()


@dataclass
class ConflictRecord:
    """Records a detected conflict and how it was resolved."""

    room: str
    field_path: str
    clients: List[str]
    strategy: str
    winner: str = ""
    ts: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.ts == 0.0:
            self.ts = time.time()


@dataclass
class MergeAuditEntry:
    """A single entry in the merge audit trail."""

    action: str
    room: str
    client_id: str = ""
    ts: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.ts == 0.0:
            self.ts = time.time()


# ── Offline queue ──


class OfflineQueue:
    """Bounded FIFO queue for offline updates with per-room isolation."""

    def __init__(self, max_size: int = MAX_PENDING):
        self._max_size = max_size
        self._queues: Dict[str, Deque[OfflineUpdate]] = defaultdict(
            lambda: deque(maxlen=max_size),
        )
        self._lock = threading.Lock()
        self._evicted_count: Dict[str, int] = defaultdict(int)

    def push(self, update: OfflineUpdate) -> bool:
        """Add an update to the queue. Returns False if the entry was evicted."""
        with self._lock:
            q = self._queues[update.room]
            was_full = len(q) >= self._max_size
            q.append(update)
            if was_full:
                self._evicted_count[update.room] += 1
                logger.debug(
                    "offline queue overflow room=%s evicted=%d",
                    update.room,
                    self._evicted_count[update.room],
                )
            return not was_full

    def drain(self, room: str) -> List[OfflineUpdate]:
        """Remove and return all pending updates for *room* in FIFO order."""
        with self._lock:
            q = self._queues.pop(room, deque())
            return list(q)

    def peek(self, room: str) -> List[OfflineUpdate]:
        with self._lock:
            return list(self._queues.get(room, []))

    def depth(self, room: str) -> int:
        with self._lock:
            return len(self._queues.get(room, []))

    def total_depth(self) -> int:
        with self._lock:
            return sum(len(q) for q in self._queues.values())

    def rooms_with_pending(self) -> List[str]:
        with self._lock:
            return [r for r, q in self._queues.items() if q]

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "rooms": len(self._queues),
                "total_pending": sum(len(q) for q in self._queues.values()),
                "evicted": dict(self._evicted_count),
            }


# ── Conflict resolver ──


class ConflictResolver:
    """Detects conflicts in a batch of offline updates and resolves them."""

    def __init__(self, default_strategy: ConflictStrategy = ConflictStrategy.LAST_WRITER_WINS):
        self._default_strategy = default_strategy
        self._field_strategies: Dict[str, ConflictStrategy] = {}
        self._pending_user_decisions: List[ConflictRecord] = []
        self._lock = threading.Lock()

    def set_strategy(self, field_path: str, strategy: ConflictStrategy) -> None:
        """Override resolution strategy for a specific field path."""
        self._field_strategies[field_path] = strategy

    def detect_conflicts(
        self,
        updates: List[OfflineUpdate],
    ) -> List[ConflictRecord]:
        """Detect conflicting updates (multiple clients editing the same field)."""
        by_field: Dict[str, List[OfflineUpdate]] = defaultdict(list)
        for u in updates:
            key = u.field_path or "__root__"
            by_field[key].append(u)

        conflicts: List[ConflictRecord] = []
        for field_path, field_updates in by_field.items():
            client_ids = list({u.client_id for u in field_updates})
            if len(client_ids) > 1:
                strategy = self._field_strategies.get(
                    field_path,
                    self._default_strategy,
                )
                conflicts.append(
                    ConflictRecord(
                        room=field_updates[0].room,
                        field_path=field_path,
                        clients=client_ids,
                        strategy=strategy.value,
                    ),
                )
        return conflicts

    def resolve(
        self,
        updates: List[OfflineUpdate],
        conflicts: List[ConflictRecord],
    ) -> List[OfflineUpdate]:
        """Apply resolution strategies and return the winning updates."""
        conflict_fields = {c.field_path for c in conflicts}

        non_conflicting = [u for u in updates if (u.field_path or "__root__") not in conflict_fields]

        resolved: List[OfflineUpdate] = list(non_conflicting)

        for conflict in conflicts:
            strategy = ConflictStrategy(conflict.strategy)
            field_updates = [u for u in updates if (u.field_path or "__root__") == conflict.field_path]

            if strategy == ConflictStrategy.LAST_WRITER_WINS:
                winner = max(field_updates, key=lambda u: u.ts)
                winner.resolved = True
                winner.resolution = "last_writer_wins"
                conflict.winner = winner.client_id
                resolved.append(winner)

            elif strategy == ConflictStrategy.MERGE:
                for u in field_updates:
                    u.resolved = True
                    u.resolution = "merged"
                conflict.winner = "all"
                resolved.extend(field_updates)

            elif strategy == ConflictStrategy.ASK_USER:
                with self._lock:
                    self._pending_user_decisions.append(conflict)
                for u in field_updates:
                    u.resolution = "pending_user"

        resolved.sort(key=lambda u: u.ts)
        return resolved

    def get_pending_decisions(self) -> List[ConflictRecord]:
        with self._lock:
            return list(self._pending_user_decisions)

    def submit_user_decision(
        self,
        field_path: str,
        room: str,
        winner_client_id: str,
    ) -> bool:
        """Submit a user's manual conflict resolution decision."""
        with self._lock:
            for i, conflict in enumerate(self._pending_user_decisions):
                if conflict.field_path == field_path and conflict.room == room:
                    conflict.winner = winner_client_id
                    conflict.strategy = "user_decision"
                    self._pending_user_decisions.pop(i)
                    return True
        return False


# ── Audit trail ──


class AuditTrail:
    """Persistent append-only log of all merge decisions."""

    def __init__(self, data_dir: str = DATA_DIR):
        self._data_dir = data_dir

    def log(self, entry: MergeAuditEntry) -> None:
        try:
            os.makedirs(self._data_dir, exist_ok=True)
            path = os.path.join(self._data_dir, f"{entry.room}.audit.jsonl")
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry)) + "\n")
        except Exception as exc:
            logger.debug("audit log write failed: %s", exc)

    def read(self, room: str, limit: int = 200) -> List[Dict[str, Any]]:
        path = os.path.join(self._data_dir, f"{room}.audit.jsonl")
        entries: List[Dict[str, Any]] = []
        if not os.path.exists(path):
            return entries
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        continue
            return entries[-limit:]
        except Exception as exc:
            logger.debug("audit read failed: %s", exc)
            return entries


# ── Main merge engine ──


class OfflineMergeEngine:
    """Coordinates offline queue, conflict resolution, and audit trail.

    Typical lifecycle:
    1. Client goes offline → updates are queued via ``enqueue()``.
    2. Client reconnects → ``reconcile()`` is called, which detects
       conflicts, applies the resolution strategy, and returns the
       result set.
    3. Caller feeds the result into ``CrdtHub.apply_update()`` to
       broadcast to the room.
    """

    def __init__(
        self,
        default_strategy: ConflictStrategy = ConflictStrategy.LAST_WRITER_WINS,
        max_pending: int = MAX_PENDING,
        on_reconcile: Optional[Callable[[str, List[OfflineUpdate]], None]] = None,
    ):
        self.queue = OfflineQueue(max_size=max_pending)
        self.resolver = ConflictResolver(default_strategy=default_strategy)
        self.audit = AuditTrail()
        self._on_reconcile = on_reconcile
        self._stats_lock = threading.Lock()
        self._reconcile_count: int = 0
        self._conflict_count: int = 0

    # ── Enqueue ──

    def enqueue(
        self,
        room: str,
        update_b64: str,
        client_id: str = "",
        field_path: str = "",
    ) -> bool:
        """Queue an offline update. Returns False if the queue overflowed."""
        update = OfflineUpdate(
            room=room,
            client_id=client_id,
            update_b64=update_b64,
            field_path=field_path,
        )
        ok = self.queue.push(update)
        self.audit.log(
            MergeAuditEntry(
                action="enqueue",
                room=room,
                client_id=client_id,
                details={"field_path": field_path, "queue_ok": ok},
            ),
        )
        return ok

    # ── Reconcile on reconnect ──

    def reconcile(self, room: str) -> Dict[str, Any]:
        """Drain the offline queue for *room*, resolve conflicts, and return a
        summary dict suitable for broadcasting to the room.
        """
        pending = self.queue.drain(room)
        if not pending:
            return {
                "room": room,
                "offline_updates": 0,
                "conflicts": 0,
                "resolved": [],
                "pending_decisions": [],
            }

        conflicts = self.resolver.detect_conflicts(pending)
        resolved = self.resolver.resolve(pending, conflicts)

        with self._stats_lock:
            self._reconcile_count += 1
            self._conflict_count += len(conflicts)

        for conflict in conflicts:
            self.audit.log(
                MergeAuditEntry(
                    action="conflict_detected",
                    room=room,
                    details={
                        "field_path": conflict.field_path,
                        "clients": conflict.clients,
                        "strategy": conflict.strategy,
                        "winner": conflict.winner,
                    },
                ),
            )

        for update in resolved:
            if update.resolved:
                self.audit.log(
                    MergeAuditEntry(
                        action="resolved",
                        room=room,
                        client_id=update.client_id,
                        details={
                            "field_path": update.field_path,
                            "resolution": update.resolution,
                        },
                    ),
                )

        if self._on_reconcile:
            try:
                self._on_reconcile(room, resolved)
            except Exception as exc:
                logger.debug("on_reconcile callback failed: %s", exc)

        self.audit.log(
            MergeAuditEntry(
                action="reconcile_complete",
                room=room,
                details={
                    "total_pending": len(pending),
                    "conflicts": len(conflicts),
                    "resolved": len(resolved),
                },
            ),
        )

        return {
            "room": room,
            "offline_updates": len(pending),
            "conflicts": len(conflicts),
            "resolved": [
                {
                    "client_id": u.client_id,
                    "field_path": u.field_path,
                    "resolution": u.resolution,
                    "ts": u.ts,
                }
                for u in resolved
            ],
            "pending_decisions": [asdict(d) for d in self.resolver.get_pending_decisions()],
        }

    # ── Stats ──

    @property
    def stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            return {
                "queue": self.queue.stats,
                "reconcile_count": self._reconcile_count,
                "conflict_count": self._conflict_count,
                "pending_user_decisions": len(
                    self.resolver.get_pending_decisions(),
                ),
            }


# ── Module-level singleton ──

_default_engine: Optional[OfflineMergeEngine] = None


def default_engine(
    strategy: ConflictStrategy = ConflictStrategy.LAST_WRITER_WINS,
) -> OfflineMergeEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = OfflineMergeEngine(default_strategy=strategy)
    return _default_engine


# ── Backward-compatible convenience functions ──


def record_offline_update(
    room: str,
    update_b64: str,
    client_id: str = "",
    field_path: str = "",
) -> None:
    """Queue an offline update (backward-compatible API)."""
    default_engine().enqueue(
        room=room,
        update_b64=update_b64,
        client_id=client_id,
        field_path=field_path,
    )


def reconcile(room: str) -> Dict[str, Any]:
    """Drain offline queue and reconcile (backward-compatible API)."""
    return default_engine().reconcile(room)


# ── Binary-level offline merge manager ──


@dataclass
class BinaryOfflineUpdate:
    """A raw binary CRDT update stored while a client was offline."""

    client_id: str
    room_id: str
    update_data: bytes
    timestamp: float = 0.0
    merged: bool = False

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class OfflineMergeManager:
    """Manages raw binary offline updates per client.

    When a client goes offline, their edits are queued here.  On
    reconnect, ``replay_on_reconnect`` feeds each queued update into
    the :class:`CrdtHub` so the CRDT merge algorithm ensures
    convergence without conflicts.

    Updates are also persisted to disk so they survive process
    restarts.
    """

    def __init__(self, storage_dir: str = "data/offline"):
        self._pending: Dict[str, List[BinaryOfflineUpdate]] = defaultdict(list)
        self._storage_dir = storage_dir
        self._lock = threading.Lock()
        self._replay_count: int = 0
        os.makedirs(storage_dir, exist_ok=True)

    def queue_update(
        self, client_id: str, room_id: str, data: bytes,
    ) -> None:
        """Queue a binary CRDT update for an offline client."""
        update = BinaryOfflineUpdate(
            client_id=client_id,
            room_id=room_id,
            update_data=data,
        )
        with self._lock:
            self._pending[client_id].append(update)
        self.persist_pending(client_id)
        logger.debug(
            "queued offline update client=%s room=%s (%d bytes)",
            client_id, room_id, len(data),
        )

    def get_pending(self, client_id: str) -> List[BinaryOfflineUpdate]:
        """Return all pending updates for a client without removing them."""
        with self._lock:
            return list(self._pending.get(client_id, []))

    async def replay_on_reconnect(self, client_id: str, hub: Any) -> int:
        """Replay all queued updates for *client_id* through the CRDT hub.

        Returns the number of updates replayed.  Each update is applied
        via ``hub.async_apply_update`` (if available) or
        ``hub.apply_update``.  Successfully replayed updates are marked
        as merged.
        """
        with self._lock:
            updates = self._pending.pop(client_id, [])
        if not updates:
            # Try loading from disk
            updates = self.load_pending(client_id)
            if not updates:
                return 0

        replayed = 0
        for update in sorted(updates, key=lambda u: u.timestamp):
            try:
                if hasattr(hub, "async_apply_update"):
                    await hub.async_apply_update(
                        update.room_id, update.client_id, update.update_data,
                    )
                else:
                    import base64 as _b64
                    hub.apply_update(
                        update.room_id,
                        _b64.b64encode(update.update_data).decode("ascii"),
                        sender_id=update.client_id,
                    )
                update.merged = True
                replayed += 1
            except Exception as exc:
                logger.warning(
                    "replay failed for client=%s room=%s: %s",
                    client_id, update.room_id, exc,
                )

        self._replay_count += replayed
        self._cleanup_disk(client_id)
        logger.info(
            "replayed %d/%d offline updates for client=%s",
            replayed, len(updates), client_id,
        )
        return replayed

    def persist_pending(self, client_id: str) -> None:
        """Save all pending updates for *client_id* to disk."""
        try:
            with self._lock:
                updates = list(self._pending.get(client_id, []))
            if not updates:
                return

            client_dir = os.path.join(self._storage_dir, client_id)
            os.makedirs(client_dir, exist_ok=True)

            manifest = []
            for i, update in enumerate(updates):
                bin_path = os.path.join(client_dir, f"{i}.bin")
                with open(bin_path, "wb") as f:
                    f.write(update.update_data)
                manifest.append({
                    "room_id": update.room_id,
                    "timestamp": update.timestamp,
                    "merged": update.merged,
                    "file": f"{i}.bin",
                })

            manifest_path = os.path.join(client_dir, "manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f)
        except Exception as exc:
            logger.debug("persist_pending failed for %s: %s", client_id, exc)

    def load_pending(self, client_id: str) -> List[BinaryOfflineUpdate]:
        """Load pending updates for *client_id* from disk."""
        client_dir = os.path.join(self._storage_dir, client_id)
        manifest_path = os.path.join(client_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            return []

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            updates: List[BinaryOfflineUpdate] = []
            for entry in manifest:
                if entry.get("merged"):
                    continue
                bin_path = os.path.join(client_dir, entry["file"])
                if not os.path.exists(bin_path):
                    continue
                with open(bin_path, "rb") as f:
                    data = f.read()
                updates.append(BinaryOfflineUpdate(
                    client_id=client_id,
                    room_id=entry["room_id"],
                    update_data=data,
                    timestamp=entry.get("timestamp", 0.0),
                ))
            return updates
        except Exception as exc:
            logger.debug("load_pending failed for %s: %s", client_id, exc)
            return []

    def _cleanup_disk(self, client_id: str) -> None:
        """Remove disk files for a client after successful replay."""
        client_dir = os.path.join(self._storage_dir, client_id)
        if not os.path.isdir(client_dir):
            return
        try:
            for fname in os.listdir(client_dir):
                os.remove(os.path.join(client_dir, fname))
            os.rmdir(client_dir)
        except Exception as exc:
            logger.debug("cleanup_disk failed for %s: %s", client_id, exc)

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = sum(len(v) for v in self._pending.values())
            return {
                "clients_with_pending": len(self._pending),
                "total_pending_updates": total,
                "total_replayed": self._replay_count,
                "storage_dir": self._storage_dir,
            }


# ── Module-level singleton for OfflineMergeManager ──

_default_merge_mgr: Optional[OfflineMergeManager] = None


def default_merge_manager(
    storage_dir: str = "data/offline",
) -> OfflineMergeManager:
    global _default_merge_mgr
    if _default_merge_mgr is None:
        _default_merge_mgr = OfflineMergeManager(storage_dir=storage_dir)
    return _default_merge_mgr
