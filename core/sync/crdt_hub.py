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

Backend support
---------------
* **In-memory** (default) – zero external dependencies.
* **Redis** (optional) – enables cross-process pub/sub, room state
  persistence across restarts, and event replay via Redis Streams.
  Falls back to in-memory gracefully when Redis is unavailable.
* **Disk persistence** – periodically saves Y.Doc state to a local
  directory so rooms survive process restarts without Redis.

This module has zero hard dependencies on FastAPI so it can also be
used from unit tests and the bot event handler.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("pilot.sync")

# ── Optional dependencies ──

try:
    import redis as _redis_lib

    _REDIS_AVAILABLE = True
except ImportError:
    _redis_lib = None  # type: ignore[assignment]
    _REDIS_AVAILABLE = False

try:  # CRDT is a "good-to-have" that degrades gracefully
    import y_py  # type: ignore[import-untyped]

    _Y_AVAILABLE = True
except Exception:  # pragma: no cover
    y_py = None  # type: ignore[assignment]
    _Y_AVAILABLE = False

# ── Presence / heartbeat constants ──

PRESENCE_STALE_SECONDS = 30
HEARTBEAT_INTERVAL_SECONDS = 15
HEARTBEAT_TIMEOUT_SECONDS = 45
_HEARTBEAT_SWEEP_INTERVAL = 5
_PERSIST_INTERVAL_SECONDS = 30

# ── Redis key helpers ──

_REDIS_CHANNEL_PREFIX = "pilot:sync:room:"
_REDIS_ROOM_STATE_PREFIX = "pilot:sync:state:"
_REDIS_STREAM_PREFIX = "pilot:sync:stream:"
_REDIS_METRICS_KEY = "pilot:sync:metrics"
_REDIS_STREAM_MAXLEN = 2000


@dataclass
class PresenceInfo:
    """Tracks a single client's presence in a room."""

    client_id: str
    user_id: str = ""
    name: str = ""
    cursor_position: Optional[Dict[str, Any]] = None
    last_active_ts: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "last_active_ts": self.last_active_ts,
            "cursor_position": self.cursor_position,
        }


@dataclass
class RoomState:
    """Full state for a single CRDT room, including doc, awareness, and
    offline queues for clients that disconnected mid-session."""

    room_id: str
    doc_state: bytes = b""
    clients: Set[str] = field(default_factory=set)
    awareness: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    last_update: float = 0.0
    pending_updates: List[Tuple[str, bytes]] = field(default_factory=list)

    def __post_init__(self):
        if self.last_update == 0.0:
            self.last_update = time.time()

    def queue_for_offline(self, client_id: str, update: bytes) -> None:
        """Queue an update destined for a disconnected client."""
        self.pending_updates.append((client_id, update))

    def drain_pending(self, client_id: str) -> List[bytes]:
        """Return and remove all queued updates for *client_id*."""
        kept: List[Tuple[str, bytes]] = []
        drained: List[bytes] = []
        for cid, data in self.pending_updates:
            if cid == client_id:
                drained.append(data)
            else:
                kept.append((cid, data))
        self.pending_updates = kept
        return drained


# ── Redis backend ──


class _RedisBackend:
    """Wraps Redis pub/sub, state persistence, and stream replay.

    Every public method is safe to call even after Redis goes away –
    failures are logged and the caller falls back to in-memory.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self._url = redis_url
        self._client: Optional[Any] = None
        self._pubsub: Optional[Any] = None
        self._listener_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._room_callbacks: Dict[str, List[Callable[[Dict[str, Any]], None]]] = defaultdict(list)
        self._lock = threading.Lock()
        self._connected = False
        self._connect()

    # ── connection ──

    def _connect(self) -> bool:
        if not _REDIS_AVAILABLE:
            return False
        try:
            self._client = _redis_lib.Redis.from_url(
                self._url,
                decode_responses=True,
                socket_connect_timeout=3,
            )
            self._client.ping()
            self._connected = True
            logger.info("Redis backend connected: %s", self._url)
            return True
        except Exception as exc:
            logger.warning("Redis unavailable (%s) – falling back to in-memory", exc)
            self._client = None
            self._connected = False
            return False

    @property
    def available(self) -> bool:
        return self._connected and self._client is not None

    # ── pub/sub ──

    def publish(self, room: str, payload: Dict[str, Any]) -> bool:
        if not self.available:
            return False
        try:
            channel = f"{_REDIS_CHANNEL_PREFIX}{room}"
            self._client.publish(channel, json.dumps(payload))  # type: ignore[union-attr]
            return True
        except Exception as exc:
            logger.debug("Redis publish failed: %s", exc)
            self._mark_down()
            return False

    def subscribe_room(
        self,
        room: str,
        callback: Callable[[Dict[str, Any]], None],
    ) -> bool:
        if not self.available:
            return False
        with self._lock:
            self._room_callbacks[room].append(callback)
            if self._pubsub is None:
                try:
                    self._pubsub = self._client.pubsub(ignore_subscribe_messages=True)  # type: ignore[union-attr]
                except Exception:
                    self._mark_down()
                    return False
        channel = f"{_REDIS_CHANNEL_PREFIX}{room}"
        try:
            self._pubsub.subscribe(channel)
            self._ensure_listener()
            return True
        except Exception as exc:
            logger.debug("Redis subscribe failed: %s", exc)
            self._mark_down()
            return False

    def _ensure_listener(self) -> None:
        with self._lock:
            if self._listener_thread is not None and self._listener_thread.is_alive():
                return
            self._listener_thread = threading.Thread(
                target=self._listen_loop,
                daemon=True,
                name="redis-sync-listener",
            )
            self._listener_thread.start()

    def _listen_loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self._pubsub is None:
                    break
                msg = self._pubsub.get_message(timeout=1.0)
                if msg and msg["type"] == "message":
                    channel: str = msg["channel"]
                    room = channel.removeprefix(_REDIS_CHANNEL_PREFIX)
                    try:
                        payload = json.loads(msg["data"])
                    except Exception:
                        continue
                    with self._lock:
                        cbs = list(self._room_callbacks.get(room, []))
                    for cb in cbs:
                        try:
                            cb(payload)
                        except Exception as e:
                            logger.debug("crdt room callback failed: %s", e)
            except Exception:
                time.sleep(0.5)

    # ── room state persistence ──

    def save_room_state(self, room: str, state_b64: str) -> bool:
        if not self.available or not state_b64:
            return False
        try:
            key = f"{_REDIS_ROOM_STATE_PREFIX}{room}"
            self._client.set(key, state_b64)  # type: ignore[union-attr]
            return True
        except Exception as exc:
            logger.debug("Redis save_room_state failed: %s", exc)
            self._mark_down()
            return False

    def load_room_state(self, room: str) -> Optional[str]:
        if not self.available:
            return None
        try:
            key = f"{_REDIS_ROOM_STATE_PREFIX}{room}"
            val = self._client.get(key)  # type: ignore[union-attr]
            return val if val else None
        except Exception:
            self._mark_down()
            return None

    # ── stream replay ──

    def append_stream(self, room: str, payload: Dict[str, Any]) -> bool:
        if not self.available:
            return False
        try:
            stream_key = f"{_REDIS_STREAM_PREFIX}{room}"
            self._client.xadd(  # type: ignore[union-attr]
                stream_key,
                {"data": json.dumps(payload)},
                maxlen=_REDIS_STREAM_MAXLEN,
                approximate=True,
            )
            return True
        except Exception as exc:
            logger.debug("Redis xadd failed: %s", exc)
            self._mark_down()
            return False

    def replay_stream(
        self,
        room: str,
        since_ms: int = 0,
        count: int = 500,
    ) -> List[Dict[str, Any]]:
        """Return events from the Redis stream for *room* since *since_ms*."""
        if not self.available:
            return []
        try:
            stream_key = f"{_REDIS_STREAM_PREFIX}{room}"
            start_id = f"{since_ms}-0" if since_ms else "0-0"
            raw = self._client.xrange(stream_key, min=start_id, count=count)  # type: ignore[union-attr]
            results: List[Dict[str, Any]] = []
            for _id, fields in raw:
                try:
                    results.append(json.loads(fields.get("data", "{}")))
                except Exception:
                    continue
            return results
        except Exception as exc:
            logger.debug("Redis replay_stream failed: %s", exc)
            self._mark_down()
            return []

    # ── metrics ──

    def incr_metric(self, field_name: str, amount: int = 1) -> None:
        if not self.available:
            return
        try:
            self._client.hincrby(_REDIS_METRICS_KEY, field_name, amount)  # type: ignore[union-attr]
        except Exception:
            pass  # redis metrics are best-effort

    def get_metrics(self) -> Dict[str, int]:
        if not self.available:
            return {}
        try:
            raw = self._client.hgetall(_REDIS_METRICS_KEY)  # type: ignore[union-attr]
            return {k: int(v) for k, v in raw.items()}
        except Exception:
            return {}

    # ── lifecycle ──

    def _mark_down(self) -> None:
        self._connected = False
        logger.debug("Redis marked as unavailable")

    def shutdown(self) -> None:
        self._stop.set()
        try:
            if self._pubsub:
                self._pubsub.close()
        except Exception as e:
            logger.debug("pubsub close failed: %s", e)
        try:
            if self._client:
                self._client.close()
        except Exception as e:
            logger.debug("redis client close failed: %s", e)


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
    def __init__(
        self,
        history_size: int = 200,
        redis_url: Optional[str] = None,
        enable_redis: bool = True,
        persist_dir: str = "data/crdt",
    ):
        self._subs: Dict[str, Subscriber] = {}
        self._by_room: Dict[str, Set[str]] = defaultdict(set)
        self._history: Dict[str, Deque[Dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=history_size),
        )
        self._ydocs: Dict[str, Any] = {}
        self._room_states: Dict[str, RoomState] = {}
        self._lock = threading.Lock()

        # Disk persistence directory
        self._persist_dir = persist_dir
        os.makedirs(persist_dir, exist_ok=True)

        # Presence: room -> client_id -> PresenceInfo
        self._presence: Dict[str, Dict[str, PresenceInfo]] = defaultdict(dict)

        # Heartbeat: client_id -> last_ping_ts
        self._last_ping: Dict[str, float] = {}

        # Pending CRDT updates per room per client (for conflict detection)
        self._pending_updates: Dict[str, Dict[str, float]] = defaultdict(dict)

        # WebSocket references for async send
        self._ws_refs: Dict[str, Any] = {}

        # Connection stats
        self._start_ts: float = time.time()
        self._msg_count: int = 0
        self._connect_count: int = 0
        self._disconnect_count: int = 0

        # Redis backend (optional)
        self._redis: Optional[_RedisBackend] = None
        if enable_redis and _REDIS_AVAILABLE:
            url = redis_url or "redis://localhost:6379/0"
            try:
                self._redis = _RedisBackend(url)
                if not self._redis.available:
                    self._redis = None
            except Exception:
                self._redis = None

        # Heartbeat reaper daemon
        self._reaper_stop = threading.Event()
        self._reaper_thread = threading.Thread(
            target=self._reaper_loop,
            daemon=True,
            name="crdt-heartbeat-reaper",
        )
        self._reaper_thread.start()

        # Periodic disk persistence daemon
        self._persist_thread = threading.Thread(
            target=self._persist_loop,
            daemon=True,
            name="crdt-disk-persist",
        )
        self._persist_thread.start()

    @property
    def redis_available(self) -> bool:
        return self._redis is not None and self._redis.available

    # ── Subscriptions ──

    def subscribe(
        self,
        client_id: str,
        send_fn: Callable[[Dict[str, Any]], None],
    ) -> Subscriber:
        with self._lock:
            sub = Subscriber(client_id, send_fn)
            self._subs[client_id] = sub
            self._last_ping[client_id] = time.time()
            self._connect_count += 1
        if self._redis:
            self._redis.incr_metric("total_connects")
        logger.info("sync subscribe client=%s total=%d", client_id, len(self._subs))
        return sub

    def unsubscribe(self, client_id: str) -> None:
        with self._lock:
            sub = self._subs.pop(client_id, None)
            if not sub:
                return
            for room in sub.rooms:
                self._by_room[room].discard(client_id)
                self._presence.get(room, {}).pop(client_id, None)
            self._last_ping.pop(client_id, None)
            self._disconnect_count += 1
        if self._redis:
            self._redis.incr_metric("total_disconnects")

    def join(self, client_id: str, room: str) -> List[Dict[str, Any]]:
        with self._lock:
            sub = self._subs.get(client_id)
            if not sub:
                return []
            sub.rooms.add(room)
            self._by_room[room].add(client_id)
            history = list(self._history.get(room, []))
            self._ensure_room_state(room).clients.add(client_id)

        # Restore YDoc state: try disk first, then Redis
        if _Y_AVAILABLE and room not in self._ydocs:
            restored = self.restore_room(room)
            if restored:
                try:
                    ydoc = y_py.YDoc()
                    y_py.apply_update(ydoc, restored)
                    with self._lock:
                        self._ydocs[room] = ydoc
                    logger.info("restored YDoc for room=%s from disk", room)
                except Exception as exc:
                    logger.debug("disk restore failed: %s", exc)

            if room not in self._ydocs and self._redis:
                saved = self._redis.load_room_state(room)
                if saved:
                    try:
                        ydoc = y_py.YDoc()
                        y_py.apply_update(ydoc, base64.b64decode(saved))
                        with self._lock:
                            self._ydocs[room] = ydoc
                        logger.info("restored YDoc for room=%s from Redis", room)
                    except Exception as exc:
                        logger.debug("failed to restore YDoc from Redis: %s", exc)

        return history

    def join_with_replay(
        self,
        client_id: str,
        room: str,
        since_ms: int = 0,
    ) -> List[Dict[str, Any]]:
        """Join a room and replay missed events from the Redis stream.

        Falls back to in-memory history when Redis is unavailable.
        """
        history = self.join(client_id, room)
        if self._redis and since_ms > 0:
            replayed = self._redis.replay_stream(room, since_ms=since_ms)
            if replayed:
                return replayed
        return history

    def leave(self, client_id: str, room: str) -> None:
        with self._lock:
            sub = self._subs.get(client_id)
            if sub:
                sub.rooms.discard(room)
            self._by_room[room].discard(client_id)
            rs = self._room_states.get(room)
            if rs:
                rs.clients.discard(client_id)
                rs.awareness.pop(client_id, None)

    def rooms(self) -> List[str]:
        with self._lock:
            return list(self._by_room.keys())

    def room_clients(self, room: str) -> List[str]:
        with self._lock:
            return list(self._by_room.get(room, set()))

    # ── Async room management (WebSocket-native) ──

    def _ensure_room_state(self, room_id: str) -> RoomState:
        """Get or create a RoomState; restores from disk if available."""
        if room_id not in self._room_states:
            rs = RoomState(room_id=room_id)
            restored = self.restore_room(room_id)
            if restored:
                rs.doc_state = restored
                if _Y_AVAILABLE and room_id not in self._ydocs:
                    try:
                        ydoc = y_py.YDoc()
                        y_py.apply_update(ydoc, restored)
                        self._ydocs[room_id] = ydoc
                        logger.info("restored YDoc from disk for room=%s", room_id)
                    except Exception as exc:
                        logger.debug("disk YDoc restore failed: %s", exc)
            self._room_states[room_id] = rs
        return self._room_states[room_id]

    async def join_room(self, room_id: str, client_id: str, ws: Any = None) -> None:
        """Async join: register a WS client, replay queued updates."""
        self.join(client_id, room_id)

        if ws is not None:
            with self._lock:
                self._ws_refs[client_id] = ws

        with self._lock:
            rs = self._ensure_room_state(room_id)
            rs.clients.add(client_id)

        # Send current doc state so the new client hydrates immediately
        state = await self.get_state(room_id)
        if state and ws is not None:
            try:
                msg = json.dumps({
                    "kind": "ystate",
                    "room": room_id,
                    "state_b64": base64.b64encode(state).decode("ascii"),
                    "ts": int(time.time() * 1000),
                })
                await ws.send_text(msg)
            except Exception as exc:
                logger.debug("send initial state failed: %s", exc)

        # Replay any updates that were queued while this client was offline
        with self._lock:
            queued = rs.drain_pending(client_id)
        if queued and ws is not None:
            for update_bytes in queued:
                try:
                    msg = json.dumps({
                        "kind": "yupdate",
                        "room": room_id,
                        "sender": "__replay__",
                        "update_b64": base64.b64encode(update_bytes).decode("ascii"),
                        "ts": int(time.time() * 1000),
                    })
                    await ws.send_text(msg)
                except Exception as exc:
                    logger.debug("replay queued update failed: %s", exc)
            logger.info(
                "replayed %d queued updates for client=%s room=%s",
                len(queued), client_id, room_id,
            )

    async def leave_room(self, room_id: str, client_id: str) -> None:
        """Async leave: remove client and clean up WS ref."""
        self.leave(client_id, room_id)
        with self._lock:
            self._ws_refs.pop(client_id, None)

    async def async_apply_update(
        self, room_id: str, client_id: str, update: bytes,
    ) -> None:
        """Apply a binary CRDT update and relay to all room members.

        Disconnected clients get the update queued for later replay.
        """
        now = time.time()

        with self._lock:
            rs = self._ensure_room_state(room_id)

        # Apply to local Y.Doc if available
        if _Y_AVAILABLE:
            try:
                ydoc = self.get_ydoc(room_id)
                if ydoc is not None:
                    y_py.apply_update(ydoc, update)
                    rs.doc_state = y_py.encode_state_as_update(ydoc)
            except Exception as exc:
                logger.warning("async yjs apply_update failed: %s", exc)
        else:
            rs.doc_state = update
        rs.last_update = now

        update_b64 = base64.b64encode(update).decode("ascii")
        payload = json.dumps({
            "kind": "yupdate",
            "room": room_id,
            "sender": client_id,
            "update_b64": update_b64,
            "ts": int(now * 1000),
        })

        # Relay to all room clients; queue for disconnected ones
        with self._lock:
            room_clients = list(rs.clients)

        for cid in room_clients:
            if cid == client_id:
                continue
            ws = self._ws_refs.get(cid)
            if ws is not None:
                try:
                    await ws.send_text(payload)
                except Exception:
                    rs.queue_for_offline(cid, update)
                    logger.debug("queued update for disconnected client=%s", cid)
            else:
                rs.queue_for_offline(cid, update)

        # Also fanout via the synchronous path for non-WS subscribers
        self.apply_update(room_id, update_b64, sender_id=client_id)

    async def get_state(self, room_id: str) -> bytes:
        """Return the current merged Y.Doc state for a room."""
        with self._lock:
            rs = self._room_states.get(room_id)

        if _Y_AVAILABLE:
            ydoc = self.get_ydoc(room_id)
            if ydoc is not None:
                try:
                    return y_py.encode_state_as_update(ydoc)
                except Exception:
                    pass

        if rs and rs.doc_state:
            return rs.doc_state

        restored = self.restore_room(room_id)
        return restored if restored else b""

    # ── Awareness protocol ──

    def update_awareness(
        self, room_id: str, client_id: str, state: Dict[str, Any],
    ) -> None:
        """Update awareness state (cursor position, selection, user info)."""
        with self._lock:
            rs = self._ensure_room_state(room_id)
            rs.awareness[client_id] = {
                **state,
                "ts": time.time(),
            }
        self.update_presence(client_id, room_id, state)

        payload = {
            "kind": "awareness",
            "room": room_id,
            "client_id": client_id,
            "state": state,
            "ts": int(time.time() * 1000),
        }
        self._fanout(room_id, payload)

    def get_awareness(self, room_id: str) -> Dict[str, Dict[str, Any]]:
        """Return all awareness states for a room."""
        with self._lock:
            rs = self._room_states.get(room_id)
            if rs is None:
                return {}
            now = time.time()
            return {
                cid: state for cid, state in rs.awareness.items()
                if now - state.get("ts", 0) < PRESENCE_STALE_SECONDS
            }

    # ── Disk persistence ──

    def persist_room(self, room_id: str) -> None:
        """Save Y.Doc state to disk."""
        try:
            state = b""
            if _Y_AVAILABLE:
                ydoc = self._ydocs.get(room_id)
                if ydoc is not None:
                    state = y_py.encode_state_as_update(ydoc)
            else:
                rs = self._room_states.get(room_id)
                if rs:
                    state = rs.doc_state

            if not state:
                return

            path = os.path.join(self._persist_dir, f"{room_id}.ystate")
            tmp_path = path + ".tmp"
            with open(tmp_path, "wb") as f:
                f.write(state)
            os.replace(tmp_path, path)
            logger.debug("persisted room=%s (%d bytes)", room_id, len(state))
        except Exception as exc:
            logger.debug("persist_room failed for %s: %s", room_id, exc)

    def restore_room(self, room_id: str) -> Optional[bytes]:
        """Load Y.Doc state from disk."""
        path = os.path.join(self._persist_dir, f"{room_id}.ystate")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                data = f.read()
            if data:
                logger.debug("restored room=%s from disk (%d bytes)", room_id, len(data))
                return data
        except Exception as exc:
            logger.debug("restore_room failed for %s: %s", room_id, exc)
        return None

    def _persist_loop(self) -> None:
        """Background daemon that periodically saves all active rooms."""
        while not self._reaper_stop.is_set():
            self._reaper_stop.wait(_PERSIST_INTERVAL_SECONDS)
            if self._reaper_stop.is_set():
                break
            with self._lock:
                active_rooms = list(self._room_states.keys())
            for room_id in active_rooms:
                self.persist_room(room_id)
                self._persist_room_state(room_id)

    # ── Broadcast primitives ──

    def _fanout(self, room: str, payload: Dict[str, Any]) -> int:
        with self._lock:
            client_ids = list(self._by_room.get(room, set()))
            subs = [self._subs[c] for c in client_ids if c in self._subs]
            self._history[room].append(payload)
            self._msg_count += 1
        for s in subs:
            s.send(payload)

        # Publish to Redis for cross-process fanout and stream replay
        if self._redis:
            self._redis.publish(room, payload)
            self._redis.append_stream(room, payload)
            self._redis.incr_metric("total_messages")

        return len(subs)

    def publish_event(self, room: str, event: Dict[str, Any]) -> int:
        payload = {
            "kind": "event",
            "room": room,
            "ts": int(time.time() * 1000),
            "event": event,
        }
        return self._fanout(room, payload)

    def publish_state(self, room: str, state: Dict[str, Any]) -> int:
        payload = {
            "kind": "state",
            "room": room,
            "ts": int(time.time() * 1000),
            "state": state,
        }
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
        """Apply a binary Yjs update and relay to everyone else in the room.

        If another client has a pending (recently applied) update on the same
        room, a ``conflict_detected`` event is emitted to all room members so
        that the UI can visualize the concurrent edit.
        """
        now = time.time()

        # ── Conflict detection ──
        with self._lock:
            pending = self._pending_updates[room]
            conflicting_clients = [cid for cid, ts in pending.items() if cid != sender_id and (now - ts) < 2.0]
            pending[sender_id] = now

        if conflicting_clients:
            conflict_payload = {
                "kind": "event",
                "room": room,
                "ts": int(now * 1000),
                "event": {
                    "type": "conflict_detected",
                    "sender": sender_id,
                    "conflicting_clients": conflicting_clients,
                    "description": (
                        f"Client {sender_id} applied an update that conflicts "
                        f"with pending updates from: {', '.join(conflicting_clients)}"
                    ),
                },
            }
            self._fanout(room, conflict_payload)

        # ── Apply CRDT merge ──
        if _Y_AVAILABLE:
            try:
                update_bytes = base64.b64decode(update_b64)
                ydoc = self.get_ydoc(room)
                if ydoc is not None:
                    y_py.apply_update(ydoc, update_bytes)
                    self._persist_room_state(room)
            except Exception as e:
                logger.warning("yjs apply_update failed: %s", e)

        payload = {
            "kind": "yupdate",
            "room": room,
            "sender": sender_id,
            "update_b64": update_b64,
            "ts": int(now * 1000),
        }
        return self._fanout(room, payload)

    def _persist_room_state(self, room: str) -> None:
        """Persist YDoc state to Redis (best-effort, non-blocking)."""
        if not self._redis or not _Y_AVAILABLE:
            return
        try:
            ydoc = self._ydocs.get(room)
            if ydoc is None:
                return
            update = y_py.encode_state_as_update(ydoc)
            state_b64 = base64.b64encode(update).decode("ascii")
            self._redis.save_room_state(room, state_b64)
        except Exception as exc:
            logger.debug("room state persist failed: %s", exc)

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

    # ── Presence awareness ──

    def update_presence(
        self,
        client_id: str,
        room: str,
        user_info: dict,
    ) -> None:
        """Update (or create) presence info for *client_id* in *room*.

        ``user_info`` may contain ``user_id``, ``name``, ``cursor_position``,
        plus arbitrary extra keys.  Called on join and on every activity ping.
        """
        now = time.time()
        with self._lock:
            info = self._presence[room].get(client_id)
            if info is None:
                info = PresenceInfo(client_id=client_id)
                self._presence[room][client_id] = info
            info.user_id = user_info.get("user_id", info.user_id)
            info.name = user_info.get("name", info.name)
            info.cursor_position = user_info.get(
                "cursor_position",
                info.cursor_position,
            )
            info.last_active_ts = now
            info.extra = {k: v for k, v in user_info.items() if k not in ("user_id", "name", "cursor_position")}
            self._last_ping[client_id] = now

    def get_presence(self, room: str) -> List[Dict[str, Any]]:
        """Return active presence list for *room*.

        Entries older than ``PRESENCE_STALE_SECONDS`` are automatically purged.
        """
        now = time.time()
        result: List[Dict[str, Any]] = []
        stale_ids: List[str] = []
        with self._lock:
            room_presence = self._presence.get(room, {})
            for cid, info in room_presence.items():
                if now - info.last_active_ts > PRESENCE_STALE_SECONDS:
                    stale_ids.append(cid)
                else:
                    result.append(info.to_dict())
            for cid in stale_ids:
                room_presence.pop(cid, None)
        return result

    # ── Heartbeat mechanism ──

    def handle_ping(self, client_id: str) -> None:
        """Record a heartbeat ping from *client_id*.

        Clients are expected to ping every ``HEARTBEAT_INTERVAL_SECONDS`` (15 s).
        If no ping is received for ``HEARTBEAT_TIMEOUT_SECONDS`` (45 s) the
        client is considered disconnected and cleaned up automatically.
        """
        with self._lock:
            if client_id in self._subs:
                self._last_ping[client_id] = time.time()

    def _reaper_loop(self) -> None:
        """Background daemon that detects timed-out clients."""
        while not self._reaper_stop.is_set():
            self._reaper_stop.wait(_HEARTBEAT_SWEEP_INTERVAL)
            if self._reaper_stop.is_set():
                break
            self._sweep_stale_clients()

    def _sweep_stale_clients(self) -> None:
        now = time.time()
        timed_out: List[str] = []
        with self._lock:
            for cid, ts in list(self._last_ping.items()):
                if now - ts > HEARTBEAT_TIMEOUT_SECONDS:
                    timed_out.append(cid)

        for cid in timed_out:
            logger.info("heartbeat timeout client=%s – disconnecting", cid)
            rooms_to_notify: List[str] = []
            with self._lock:
                sub = self._subs.get(cid)
                if sub:
                    rooms_to_notify = list(sub.rooms)
            self.unsubscribe(cid)
            for room in rooms_to_notify:
                self._fanout(
                    room,
                    {
                        "kind": "event",
                        "room": room,
                        "ts": int(now * 1000),
                        "event": {
                            "type": "client_disconnected",
                            "client_id": cid,
                        },
                    },
                )

    def shutdown(self) -> None:
        """Stop background threads, persist all rooms, and release resources."""
        self._reaper_stop.set()
        self._reaper_thread.join(timeout=3)
        self._persist_thread.join(timeout=3)

        # Final persist of all active rooms before shutdown
        with self._lock:
            active_rooms = list(self._room_states.keys())
        for room_id in active_rooms:
            self.persist_room(room_id)

        if self._redis:
            self._redis.shutdown()

    # ── Connection & Redis stats ──

    def get_stats(self) -> Dict[str, Any]:
        """Return live connection statistics.

        Returns a dict with ``total_clients``, ``total_rooms``,
        ``messages_per_sec``, ``uptime_seconds``, and Redis info if available.
        """
        now = time.time()
        uptime = max(now - self._start_ts, 0.001)
        with self._lock:
            pending_total = sum(
                len(rs.pending_updates)
                for rs in self._room_states.values()
            )
            stats: Dict[str, Any] = {
                "total_clients": len(self._subs),
                "total_rooms": len(self._by_room),
                "messages_per_sec": round(self._msg_count / uptime, 2),
                "total_messages": self._msg_count,
                "total_connects": self._connect_count,
                "total_disconnects": self._disconnect_count,
                "uptime_seconds": round(uptime, 1),
                "redis_available": self.redis_available,
                "y_py_available": _Y_AVAILABLE,
                "room_states": len(self._room_states),
                "queued_offline_updates": pending_total,
                "persist_dir": self._persist_dir,
            }

        if self._redis:
            redis_metrics = self._redis.get_metrics()
            if redis_metrics:
                stats["redis_metrics"] = redis_metrics

        return stats


# ── Module singleton ──

_default: Optional[CrdtHub] = None


def default_hub(
    redis_url: Optional[str] = None,
    enable_redis: bool = True,
    persist_dir: str = "data/crdt",
) -> CrdtHub:
    global _default
    if _default is None:
        _default = CrdtHub(
            redis_url=redis_url,
            enable_redis=enable_redis,
            persist_dir=persist_dir,
        )
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
    except Exception as e:
        logger.debug("set_broadcaster for orchestrator failed: %s", e)
