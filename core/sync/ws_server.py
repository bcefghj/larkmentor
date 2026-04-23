"""FastAPI WebSocket server mounted on the existing dashboard.

Endpoints
---------
* ``GET /sync/health`` – quick health probe.
* ``GET /sync/rooms`` – list active rooms + client counts.
* ``WS  /sync/ws``   – bidirectional WebSocket. Protocol:

    client → server
      {"op": "join",     "room": "<plan_id>", "client_id": "..."}
      {"op": "leave",    "room": "<plan_id>"}
      {"op": "state",    "room": "<plan_id>", "state": {...}}
      {"op": "yupdate",  "room": "<plan_id>", "update_b64": "..."}
      {"op": "ping"}

    server → client
      {"kind": "event",    "room": "...", "event": {...}, "ts": ...}
      {"kind": "state",    "room": "...", "state": {...}, "ts": ...}
      {"kind": "yupdate",  "room": "...", "update_b64": "...", "sender": "..."}
      {"kind": "history",  "room": "...", "items": [...]}
      {"kind": "snapshot", "room": "...", "update_b64": "..."}
      {"kind": "pong"}

The router is importable as ``core.sync.ws_server.router`` and already
mounted from ``dashboard/server.py`` when available.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict

from .crdt_hub import default_hub

logger = logging.getLogger("pilot.sync.ws")

try:
    from fastapi import APIRouter, WebSocket, WebSocketDisconnect
    _FASTAPI = True
except Exception:  # pragma: no cover
    APIRouter = None  # type: ignore
    WebSocket = None  # type: ignore
    WebSocketDisconnect = Exception  # type: ignore
    _FASTAPI = False


router = APIRouter(prefix="/sync") if _FASTAPI else None


if _FASTAPI:

    @router.get("/health")
    def health() -> Dict[str, Any]:
        hub = default_hub()
        return {"ok": True, "rooms": hub.rooms(), "client_count": sum(1 for _ in hub._subs)}

    @router.get("/rooms")
    def rooms_summary() -> Dict[str, Any]:
        hub = default_hub()
        out = {}
        for r in hub.rooms():
            out[r] = {"clients": hub.room_clients(r)}
        return {"rooms": out}

    @router.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        hub = default_hub()
        client_id = f"ws_{uuid.uuid4().hex[:8]}"
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        loop = asyncio.get_event_loop()

        def _send(payload: Dict[str, Any]) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, payload)
            except Exception:
                pass

        sub = hub.subscribe(client_id, _send)
        await ws.send_text(json.dumps({"kind": "hello", "client_id": client_id}))

        async def _sender():
            while True:
                payload = await queue.get()
                try:
                    await ws.send_text(json.dumps(payload, ensure_ascii=False))
                except Exception:
                    break

        sender_task = asyncio.create_task(_sender())

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except Exception:
                    await ws.send_text(json.dumps({"kind": "error", "reason": "bad_json"}))
                    continue
                op = msg.get("op")
                room = msg.get("room", "")

                if op == "ping":
                    await ws.send_text(json.dumps({"kind": "pong"}))
                elif op == "join" and room:
                    history = hub.join(client_id, room)
                    await ws.send_text(json.dumps({
                        "kind": "history", "room": room, "items": history,
                    }, ensure_ascii=False))
                    snap = hub.snapshot(room)
                    if snap:
                        await ws.send_text(json.dumps({
                            "kind": "snapshot", "room": room, "update_b64": snap,
                        }))
                elif op == "leave" and room:
                    hub.leave(client_id, room)
                elif op == "state" and room:
                    hub.publish_state(room, msg.get("state") or {})
                elif op == "yupdate" and room:
                    hub.apply_update(room, msg.get("update_b64", ""), sender_id=client_id)
                else:
                    await ws.send_text(json.dumps({"kind": "error", "reason": f"unknown_op:{op}"}))
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.debug("ws loop error client=%s: %s", client_id, e)
        finally:
            hub.unsubscribe(client_id)
            sender_task.cancel()
            try:
                await ws.close()
            except Exception:
                pass
