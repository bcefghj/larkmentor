"""Working memory: bounded ring-buffer of recent events per user.

Persisted to ``data/working_memory/<open_id>.json`` so that a process
restart does not amnesia the user. Capacity defaults to 200 events; older
items get summarised into a compaction artifact (see ``compaction.py``).
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
WM_DIR = ROOT / "data" / "working_memory"
WM_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CAPACITY = 200

_locks: Dict[str, threading.Lock] = {}


def _get_lock(open_id: str) -> threading.Lock:
    if open_id not in _locks:
        _locks[open_id] = threading.Lock()
    return _locks[open_id]


@dataclass
class WorkingEvent:
    """A single event recorded inside the working memory."""

    ts: int
    kind: str  # message | decision | focus_start | focus_end | task | doc | meeting
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorkingMemory:
    """Bounded list of events for a single user."""

    open_id: str
    capacity: int = DEFAULT_CAPACITY
    events: List[WorkingEvent] = field(default_factory=list)

    def append(self, event: WorkingEvent) -> Optional[List[WorkingEvent]]:
        """Append an event. Returns the spilled events when capacity exceeded.

        The caller should hand the spilled batch to the compaction module
        for summarisation.
        """
        self.events.append(event)
        if len(self.events) <= self.capacity:
            return None
        # Spill the oldest 25% to keep churn low.
        spill_size = max(1, self.capacity // 4)
        spilled = self.events[:spill_size]
        self.events = self.events[spill_size:]
        return spilled

    def to_dict(self) -> dict:
        return {
            "open_id": self.open_id,
            "capacity": self.capacity,
            "events": [e.to_dict() for e in self.events],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorkingMemory":
        return cls(
            open_id=d["open_id"],
            capacity=d.get("capacity", DEFAULT_CAPACITY),
            events=[WorkingEvent(**e) for e in d.get("events", [])],
        )

    @classmethod
    def load(cls, open_id: str, capacity: int = DEFAULT_CAPACITY) -> "WorkingMemory":
        path = WM_DIR / f"{open_id}.json"
        if not path.exists():
            return cls(open_id=open_id, capacity=capacity)
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return cls(open_id=open_id, capacity=capacity)

    def save(self) -> None:
        with _get_lock(self.open_id):
            tmp = WM_DIR / f"{self.open_id}.json.tmp"
            tmp.write_text(
                json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, WM_DIR / f"{self.open_id}.json")

    # ── Convenience filters used by recall / dashboard ──

    def recent(self, n: int = 50, kinds: Optional[List[str]] = None) -> List[WorkingEvent]:
        items = self.events
        if kinds:
            items = [e for e in items if e.kind in kinds]
        return items[-n:]

    def since(self, ts: int) -> List[WorkingEvent]:
        return [e for e in self.events if e.ts >= ts]
