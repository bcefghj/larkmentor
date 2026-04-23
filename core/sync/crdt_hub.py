"""CRDT Hub – pub/sub state distribution for Agent-Pilot.

Design
------
* Each plan has a **room**.  Any number of clients (Flutter mobile /
  Flutter desktop / Web dashboard / Feishu Bot back-channel) can
  subscribe to the room.
* Messages are either:
    - ``{"kind": "event", ...}`` – Orchestrator events replayed to all
      clients (so late joiners immediately see current state).
    - ``{"kind": "state", ...}`` – Arbitrary tool broadcasts, e.g.
      ``canvas.shape_added``.
    - ``{"kind": "yupdate", "room": ..., "update_b64": ...}`` – binary
      Yjs document updates (base64 encoded). When y-py is installed the
      hub applies them to a persistent ``YDoc`` so that new clients
      synchronise from the merged state.
* All subscribers are thread-safe references; the hub itself is a
  singleton living in the FastAPI process.

This module has zero hard dependencies on FastAPI so it can also be
used from unit tests and the bot event handler.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any, Callable, Deque, Dict, List, Optional, Set

logger = logging.getLogger("pilot.sync")

try:  # Optional dependency – CRDT is a "good-to-have" that degrades gracefully
    import y_py  # type: ignore
    _Y_AVAILABLE = True
except Exception:  # pragma: no cover
    y_py = None  # type: ignore
    _Y_AVAILABLE = False


class Subscriber:
    """A connected client."""

    def __init__(self, client_id: str, send_fn: Callable[[Dict[str, Any]], None]):
        self.client_id = client_id
        self._send = send_fn
        self.rooms: Set[str] = set()

    def send(self, payload: Dict[str, Any]) -> None:
        try:
            self._send(payload)
        except Exception as e:
            logger.debug("subscriber send failed %s: %s", self.client_id, e)


class CrdtHub:

    def __init__(self, history_size: int = 200):
        self._subs: Dict[str, Subscriber] = {}
        self._by_room: Dict[str, Set[str]] = defaultdict(set)
        self._history: Dict[str, Deque[Dict[str, Any]]] = defaultdict(lambda: deque(maxlen=history_size))
        self._ydocs: Dict[str, Any] = {}
        self._lock = threading.Lock()

    # ── Subscriptions ──

    def subscribe(self, client_id: str, send_fn: Callable[[Dict[str, Any]], None]) -> Subscriber:
        with self._lock:
            sub = Subscriber(client_id, send_fn)
            self._subs[client_id] = sub
        logger.info("sync subscribe client=%s total=%d", client_id, len(self._subs))
        return sub

    def unsubscribe(self, client_id: str) -> None:
        with self._lock:
            sub = self._subs.pop(client_id, None)
            if not sub:
                return
            for room in sub.rooms:
                self._by_room[room].discard(client_id)

    def join(self, client_id: str, room: str) -> List[Dict[str, Any]]:
        with self._lock:
            sub = self._subs.get(client_id)
            if not sub:
                return []
            sub.rooms.add(room)
            self._by_room[room].add(client_id)
            return list(self._history.get(room, []))

    def leave(self, client_id: str, room: str) -> None:
        with self._lock:
            sub = self._subs.get(client_id)
            if sub:
                sub.rooms.discard(room)
            self._by_room[room].discard(client_id)

    def rooms(self) -> List[str]:
        with self._lock:
            return list(self._by_room.keys())

    def room_clients(self, room: str) -> List[str]:
        with self._lock:
            return list(self._by_room.get(room, set()))

    # ── Broadcast primitives ──

    def _fanout(self, room: str, payload: Dict[str, Any]) -> int:
        with self._lock:
            client_ids = list(self._by_room.get(room, set()))
            subs = [self._subs[c] for c in client_ids if c in self._subs]
            self._history[room].append(payload)
        for s in subs:
            s.send(payload)
        return len(subs)

    def publish_event(self, room: str, event: Dict[str, Any]) -> int:
        payload = {"kind": "event", "room": room, "ts": int(time.time() * 1000),
                   "event": event}
        return self._fanout(room, payload)

    def publish_state(self, room: str, state: Dict[str, Any]) -> int:
        payload = {"kind": "state", "room": room, "ts": int(time.time() * 1000),
                   "state": state}
        return self._fanout(room, payload)

    # ── CRDT binary path ──

    def get_ydoc(self, room: str):
        if not _Y_AVAILABLE:
            return None
        with self._lock:
            if room not in self._ydocs:
                self._ydocs[room] = y_py.YDoc()
            return self._ydocs[room]

    def apply_update(self, room: str, update_b64: str, sender_id: str = "") -> int:
        """Apply a binary Yjs update and relay to everyone else in the room."""
        if _Y_AVAILABLE:
            try:
                update_bytes = base64.b64decode(update_b64)
                ydoc = self.get_ydoc(room)
                if ydoc is not None:
                    y_py.apply_update(ydoc, update_bytes)
            except Exception as e:
                logger.warning("yjs apply_update failed: %s", e)
        # Even without y-py we still relay the opaque bytes to peers
        payload = {
            "kind": "yupdate", "room": room, "sender": sender_id,
            "update_b64": update_b64, "ts": int(time.time() * 1000),
        }
        return self._fanout(room, payload)

    def snapshot(self, room: str) -> str:
        """Return the current YDoc state as base64 so late joiners can hydrate."""
        if not _Y_AVAILABLE:
            return ""
        ydoc = self.get_ydoc(room)
        if ydoc is None:
            return ""
        try:
            update = y_py.encode_state_as_update(ydoc)
            return base64.b64encode(update).decode("ascii")
        except Exception as e:
            logger.debug("snapshot failed: %s", e)
            return ""


# ── Module singleton ──

_default: Optional[CrdtHub] = None


def default_hub() -> CrdtHub:
    global _default
    if _default is None:
        _default = CrdtHub()
    return _default


# ── Convenience helpers used by tools/orchestrator ──

def broadcast_state(plan_id: str, state: Dict[str, Any]) -> int:
    if not plan_id:
        return 0
    return default_hub().publish_state(plan_id, state)


def broadcast_event(plan_id: str, event: Dict[str, Any]) -> int:
    if not plan_id:
        return 0
    return default_hub().publish_event(plan_id, event)


def attach_orchestrator(orch) -> None:
    """Wire the orchestrator's event stream into the hub."""
    def _fn(ev):
        try:
            broadcast_event(getattr(ev, "plan_id", ""), ev.to_dict())
        except Exception as e:
            logger.debug("orchestrator bridge error: %s", e)
    try:
        orch.set_broadcaster(_fn)
    except Exception:
        pass
