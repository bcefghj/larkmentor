"""WebSocket Sync Hub — 多端实时同步 + presence + 离线 reconcile.

V1 设计:
  - 每个 plan/session 一个 Room
  - Room 内所有 client 共享一个 Y.Doc（pycrdt）
  - 新 client 加入 → 全量 sync
  - 任何 client 写 → 增量广播到所有人
  - presence 广播：online/offline 状态
  - 离线：client 离线时本地 buffer，联网后 send_state_vector + apply_update_v1 reconcile

Note: pycrdt 可选依赖。无时回退到简化的 dict-based 广播（保证 V1 可启动）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("pilot.surface.sync.hub")


@dataclass
class ClientConnection:
    client_id: str
    ws: Any  # WebSocket
    rooms: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)
    joined_at: float = field(default_factory=time.time)


@dataclass
class Room:
    room_id: str
    clients: dict[str, ClientConnection] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)  # 简化 state（CRDT 替代）
    history: list[dict[str, Any]] = field(default_factory=list)
    yjs_doc: Any = None
    created_at: float = field(default_factory=time.time)


class SyncHub:
    """轻量 sync hub —— FastAPI WebSocket 集成."""

    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._mutex = asyncio.Lock()
        self._yjs_available = self._check_yjs()

    def _check_yjs(self) -> bool:
        try:
            import pycrdt  # noqa: F401
            return True
        except ImportError:
            logger.info("pycrdt 不可用 — sync hub 走简化 dict-based 模式")
            return False

    # ── Room 管理 ──
    async def join(self, *, room_id: str, ws: Any, client_id: str = "", metadata: dict[str, Any] | None = None) -> str:
        client_id = client_id or f"client_{uuid.uuid4().hex[:8]}"
        async with self._mutex:
            room = self._rooms.get(room_id)
            if room is None:
                room = Room(room_id=room_id)
                if self._yjs_available:
                    try:
                        from pycrdt import Doc

                        room.yjs_doc = Doc()
                    except Exception:
                        room.yjs_doc = None
                self._rooms[room_id] = room
            conn = ClientConnection(client_id=client_id, ws=ws, metadata=metadata or {})
            conn.rooms.add(room_id)
            room.clients[client_id] = conn

        await self._send_to(client_id, room_id, {
            "kind": "room.joined",
            "room_id": room_id,
            "client_id": client_id,
            "history": room.history[-200:],  # 给离线 client 最近 200 条
            "state": room.state,
            "members": list(room.clients.keys()),
        })

        # presence 广播
        await self._broadcast(room_id, {
            "kind": "presence.join",
            "client_id": client_id,
            "metadata": metadata or {},
            "members": list(room.clients.keys()),
        }, except_client=client_id)

        return client_id

    async def leave(self, *, room_id: str, client_id: str) -> None:
        async with self._mutex:
            room = self._rooms.get(room_id)
            if not room:
                return
            room.clients.pop(client_id, None)
        await self._broadcast(room_id, {
            "kind": "presence.leave",
            "client_id": client_id,
            "members": list(self._rooms.get(room_id, Room("")).clients.keys()),
        })

    # ── 业务消息 ──
    async def publish(
        self,
        *,
        room_id: str,
        kind: str,
        payload: dict[str, Any],
        from_client_id: str = "",
    ) -> None:
        """业务事件（如 task_progress / step.done）写入 Room 并广播."""
        async with self._mutex:
            room = self._rooms.get(room_id)
            if not room:
                room = Room(room_id=room_id)
                self._rooms[room_id] = room
            evt = {"ts": time.time(), "kind": kind, "payload": payload, "from": from_client_id}
            room.history.append(evt)
            if len(room.history) > 2000:
                room.history = room.history[-1500:]
            # 写到 state（简化 KV 合并）
            if kind == "state.set":
                key = payload.get("key", "")
                if key:
                    room.state[key] = payload.get("value")

        await self._broadcast(room_id, {"kind": kind, "payload": payload, "from": from_client_id})

    async def yjs_apply_update(
        self,
        *,
        room_id: str,
        update_b64: str,
        from_client_id: str = "",
    ) -> None:
        """接收 Yjs binary update，apply 到 Room.yjs_doc 后广播给其他 client."""
        async with self._mutex:
            room = self._rooms.get(room_id)
            if not room:
                room = Room(room_id=room_id)
                self._rooms[room_id] = room
            # 应用到 Yjs（如果可用）
            if self._yjs_available and room.yjs_doc is not None:
                try:
                    import base64

                    update_bytes = base64.b64decode(update_b64)
                    room.yjs_doc.apply_update(update_bytes)
                except Exception as e:
                    logger.debug("yjs apply_update failed: %s", e)

        await self._broadcast(room_id, {
            "kind": "yjs.update",
            "update_b64": update_b64,
            "from": from_client_id,
        }, except_client=from_client_id)

    async def get_yjs_state_vector(self, *, room_id: str) -> str:
        """给离线 client 用：返回当前 Yjs 状态向量（base64）."""
        async with self._mutex:
            room = self._rooms.get(room_id)
            if not room or not self._yjs_available or room.yjs_doc is None:
                return ""
            try:
                import base64

                sv = room.yjs_doc.get_state()
                return base64.b64encode(sv).decode("utf-8")
            except Exception:
                return ""

    async def reconcile(self, *, room_id: str, client_state_b64: str) -> str:
        """离线 reconcile：client 提交它的 state_vector，hub 返回 diff update."""
        async with self._mutex:
            room = self._rooms.get(room_id)
            if not room or not self._yjs_available or room.yjs_doc is None:
                return ""
        try:
            import base64

            client_sv = base64.b64decode(client_state_b64) if client_state_b64 else b""
            diff = room.yjs_doc.get_update(client_sv)
            return base64.b64encode(diff).decode("utf-8")
        except Exception as e:
            logger.debug("reconcile failed: %s", e)
            return ""

    # ── Stats ──
    def stats(self) -> dict[str, Any]:
        return {
            "rooms_count": len(self._rooms),
            "rooms": [
                {
                    "room_id": r.room_id,
                    "clients": len(r.clients),
                    "history_len": len(r.history),
                    "yjs_active": r.yjs_doc is not None,
                }
                for r in self._rooms.values()
            ],
            "yjs_available": self._yjs_available,
        }

    # ── private ──
    async def _broadcast(self, room_id: str, msg: dict[str, Any], except_client: str = "") -> None:
        room = self._rooms.get(room_id)
        if not room:
            return
        text = json.dumps(msg, ensure_ascii=False)
        dead = []
        for cid, conn in room.clients.items():
            if cid == except_client:
                continue
            try:
                await conn.ws.send_text(text)
            except Exception:
                dead.append(cid)
        for cid in dead:
            room.clients.pop(cid, None)

    async def _send_to(self, client_id: str, room_id: str, msg: dict[str, Any]) -> None:
        room = self._rooms.get(room_id)
        if not room:
            return
        conn = room.clients.get(client_id)
        if not conn:
            return
        try:
            await conn.ws.send_text(json.dumps(msg, ensure_ascii=False))
        except Exception as e:
            logger.debug("_send_to failed: %s", e)


_default: SyncHub | None = None


def default_hub() -> SyncHub:
    global _default
    if _default is None:
        _default = SyncHub()
    return _default
