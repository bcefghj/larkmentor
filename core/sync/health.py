"""Sync health monitor for Agent-Pilot multi-device synchronisation.

Tracks per-room latency percentiles, connection stability, queue depth,
and conflict resolution rates. Optionally exports metrics to Prometheus
via ``prometheus_client`` (graceful degradation when not installed).

Usage::

    from core.sync.health import default_monitor

    monitor = default_monitor()
    monitor.record_sync_latency("room-123", 0.045)
    monitor.record_disconnect("room-123", "client-A")
    report = monitor.get_health_report()
"""

from __future__ import annotations

import bisect
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pilot.sync.health")

try:
    from prometheus_client import Counter, Gauge, Histogram  # type: ignore[import-untyped]

    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False

# ── Prometheus metrics (created lazily) ──

_prom_sync_latency: Any = None
_prom_connected_clients: Any = None
_prom_pending_updates: Any = None
_prom_conflicts_total: Any = None
_prom_disconnects_total: Any = None
_prom_initialized = False


def _init_prometheus() -> None:
    global _prom_sync_latency, _prom_connected_clients, _prom_pending_updates
    global _prom_conflicts_total, _prom_disconnects_total, _prom_initialized
    if _prom_initialized or not _PROM_AVAILABLE:
        return
    _prom_sync_latency = Histogram(
        "pilot_sync_latency_seconds",
        "Sync latency per room",
        ["room"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )
    _prom_connected_clients = Gauge(
        "pilot_sync_connected_clients",
        "Number of connected sync clients",
        ["room"],
    )
    _prom_pending_updates = Gauge(
        "pilot_sync_pending_updates",
        "Pending offline updates per room",
        ["room"],
    )
    _prom_conflicts_total = Counter(
        "pilot_sync_conflicts_total",
        "Total number of conflicts detected",
        ["room"],
    )
    _prom_disconnects_total = Counter(
        "pilot_sync_disconnects_total",
        "Total number of client disconnects",
        ["room"],
    )
    _prom_initialized = True
    logger.info("Prometheus metrics initialised for pilot.sync")


# ── Percentile helper ──


class _LatencyTracker:
    """Fixed-window sorted latency tracker with percentile computation.

    Keeps at most ``window_size`` samples per room and uses a sorted
    insertion strategy for O(1) percentile lookups.
    """

    def __init__(self, window_size: int = 1000):
        self._window_size = window_size
        self._samples: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def record(self, room: str, latency_sec: float) -> None:
        with self._lock:
            samples = self._samples[room]
            if len(samples) >= self._window_size:
                samples.pop(0)
            bisect.insort(samples, latency_sec)

    def percentile(self, room: str, p: float) -> float:
        """Return the *p*-th percentile (0–100) for *room*, or 0.0."""
        with self._lock:
            samples = self._samples.get(room)
            if not samples:
                return 0.0
            idx = int(len(samples) * p / 100.0)
            idx = min(idx, len(samples) - 1)
            return samples[idx]

    def count(self, room: str) -> int:
        with self._lock:
            return len(self._samples.get(room, []))

    def rooms(self) -> List[str]:
        with self._lock:
            return list(self._samples.keys())


# ── Connection stability tracker ──


@dataclass
class _ConnectionStats:
    total_connects: int = 0
    total_disconnects: int = 0
    last_disconnect_ts: float = 0.0
    disconnect_intervals: List[float] = field(default_factory=list)


class _StabilityTracker:
    """Track connect / disconnect frequency per room."""

    _MAX_INTERVALS = 200

    def __init__(self):
        self._stats: Dict[str, _ConnectionStats] = defaultdict(_ConnectionStats)
        self._lock = threading.Lock()

    def record_connect(self, room: str, client_id: str) -> None:
        with self._lock:
            self._stats[room].total_connects += 1

    def record_disconnect(self, room: str, client_id: str) -> None:
        now = time.time()
        with self._lock:
            s = self._stats[room]
            if s.last_disconnect_ts > 0:
                interval = now - s.last_disconnect_ts
                s.disconnect_intervals.append(interval)
                if len(s.disconnect_intervals) > self._MAX_INTERVALS:
                    s.disconnect_intervals = s.disconnect_intervals[-self._MAX_INTERVALS :]
            s.last_disconnect_ts = now
            s.total_disconnects += 1

    def get(self, room: str) -> Dict[str, Any]:
        with self._lock:
            s = self._stats.get(room, _ConnectionStats())
            intervals = s.disconnect_intervals
            avg_interval = sum(intervals) / len(intervals) if intervals else 0.0
            return {
                "total_connects": s.total_connects,
                "total_disconnects": s.total_disconnects,
                "avg_disconnect_interval_sec": round(avg_interval, 2),
                "last_disconnect_ts": s.last_disconnect_ts,
            }

    def rooms(self) -> List[str]:
        with self._lock:
            return list(self._stats.keys())


# ── Main monitor ──


class SyncHealthMonitor:
    """Aggregates sync health metrics across all rooms.

    Thread-safe. Designed to be used as a singleton alongside
    ``CrdtHub`` and ``OfflineMergeEngine``.
    """

    def __init__(self, enable_prometheus: bool = True):
        self._latency = _LatencyTracker()
        self._stability = _StabilityTracker()
        self._lock = threading.Lock()

        self._conflict_counts: Dict[str, int] = defaultdict(int)
        self._resolution_counts: Dict[str, int] = defaultdict(int)
        self._pending_depths: Dict[str, int] = defaultdict(int)

        self._enable_prom = enable_prometheus and _PROM_AVAILABLE
        if self._enable_prom:
            _init_prometheus()

    # ── Recording methods ──

    def record_sync_latency(self, room: str, latency_sec: float) -> None:
        self._latency.record(room, latency_sec)
        if self._enable_prom and _prom_sync_latency is not None:
            _prom_sync_latency.labels(room=room).observe(latency_sec)

    def record_connect(self, room: str, client_id: str) -> None:
        self._stability.record_connect(room, client_id)
        if self._enable_prom and _prom_connected_clients is not None:
            _prom_connected_clients.labels(room=room).inc()

    def record_disconnect(self, room: str, client_id: str) -> None:
        self._stability.record_disconnect(room, client_id)
        if self._enable_prom:
            if _prom_connected_clients is not None:
                _prom_connected_clients.labels(room=room).dec()
            if _prom_disconnects_total is not None:
                _prom_disconnects_total.labels(room=room).inc()

    def record_conflict(self, room: str) -> None:
        with self._lock:
            self._conflict_counts[room] += 1
        if self._enable_prom and _prom_conflicts_total is not None:
            _prom_conflicts_total.labels(room=room).inc()

    def record_resolution(self, room: str) -> None:
        with self._lock:
            self._resolution_counts[room] += 1

    def update_pending_depth(self, room: str, depth: int) -> None:
        with self._lock:
            self._pending_depths[room] = depth
        if self._enable_prom and _prom_pending_updates is not None:
            _prom_pending_updates.labels(room=room).set(depth)

    # ── Per-room report ──

    def get_room_health(self, room: str) -> Dict[str, Any]:
        with self._lock:
            conflicts = self._conflict_counts.get(room, 0)
            resolutions = self._resolution_counts.get(room, 0)
            pending = self._pending_depths.get(room, 0)

        resolution_rate = round(resolutions / conflicts, 3) if conflicts > 0 else 1.0

        return {
            "room": room,
            "latency": {
                "p50_sec": round(self._latency.percentile(room, 50), 4),
                "p95_sec": round(self._latency.percentile(room, 95), 4),
                "p99_sec": round(self._latency.percentile(room, 99), 4),
                "sample_count": self._latency.count(room),
            },
            "connection_stability": self._stability.get(room),
            "pending_queue_depth": pending,
            "conflicts": {
                "total": conflicts,
                "resolved": resolutions,
                "resolution_rate": resolution_rate,
            },
        }

    # ── Aggregate report ──

    def get_health_report(self) -> Dict[str, Any]:
        """Return a full health report across all tracked rooms."""
        all_rooms = set(self._latency.rooms())
        all_rooms.update(self._stability.rooms())
        with self._lock:
            all_rooms.update(self._conflict_counts.keys())
            all_rooms.update(self._pending_depths.keys())
            total_conflicts = sum(self._conflict_counts.values())
            total_resolutions = sum(self._resolution_counts.values())
            total_pending = sum(self._pending_depths.values())

        room_reports = {room: self.get_room_health(room) for room in sorted(all_rooms)}

        return {
            "ts": time.time(),
            "rooms_tracked": len(all_rooms),
            "aggregate": {
                "total_conflicts": total_conflicts,
                "total_resolutions": total_resolutions,
                "total_pending_depth": total_pending,
                "resolution_rate": (round(total_resolutions / total_conflicts, 3) if total_conflicts > 0 else 1.0),
            },
            "prometheus_enabled": self._enable_prom,
            "rooms": room_reports,
        }


# ── Module singleton ──

_default: Optional[SyncHealthMonitor] = None


def default_monitor(enable_prometheus: bool = True) -> SyncHealthMonitor:
    global _default
    if _default is None:
        _default = SyncHealthMonitor(enable_prometheus=enable_prometheus)
    return _default
