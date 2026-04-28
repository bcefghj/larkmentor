"""y-websocket protocol server (Python, 对齐 yjs/y-protocols)。

wire format (varint encoded):
- MessageType 0 = sync (sync_step_1 / sync_step_2 / sync_update)
- MessageType 1 = awareness (cursor/selection/presence)
- MessageType 2 = auth

本服务端接受 Flutter WebView 内嵌 tldraw/tiptap + y-websocket 客户端的连接，
使用 y-py 维护 YDoc 和 awareness 状态，实现真正的 CRDT 无冲突合并。

如果 y-py 未安装，退化为 JSON echo 协议（Dev 模式），但 CRDT 无法保证。
"""

from __future__ import annotations

import asyncio
import logging
import os
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("sync_v4.yws")


def _varint_encode(n: int) -> bytes:
    """Encode unsigned varint (as used by Yjs y-protocols)."""
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)


def _varint_decode(data: bytes, offset: int = 0) -> tuple:
    n = 0; shift = 0; pos = offset
    while pos < len(data):
        byte = data[pos]; pos += 1
        n |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return n, pos
        shift += 7
    raise ValueError("varint decode failed")


def _read_var_uint8_array(data: bytes, offset: int) -> tuple:
    length, pos = _varint_decode(data, offset)
    return data[pos:pos + length], pos + length


MSG_SYNC = 0
MSG_AWARENESS = 1
MSG_AUTH = 2
MSG_QUERY_AWARENESS = 3

SYNC_STEP_1 = 0
SYNC_STEP_2 = 1
SYNC_UPDATE = 2


class Room:
    """One collaborative room (e.g. one tldraw canvas or one Tiptap doc)."""
    def __init__(self, room_id: str) -> None:
        self.room_id = room_id
        self.clients: Set[Any] = set()
        self.awareness: Dict[int, Dict] = {}
        self._init_ydoc()

    def _init_ydoc(self) -> None:
        try:
            import y_py as Y  # type: ignore
            self.ydoc = Y.YDoc()
            self._ypy = True
        except ImportError:
            logger.warning("y_py not installed, using JSON fallback (CRDT disabled)")
            self.ydoc = None
            self._ypy = False

    async def broadcast(self, msg: bytes, *, exclude: Any = None) -> None:
        dead = []
        for client in list(self.clients):
            if client is exclude:
                continue
            try:
                await client.send_bytes(msg)
            except Exception:
                dead.append(client)
        for d in dead:
            self.clients.discard(d)


class YWSServer:
    def __init__(self, *, host: str = "0.0.0.0", port: int = 8002) -> None:
        self.host = host
        self.port = port
        self.rooms: Dict[str, Room] = {}

    def get_room(self, room_id: str) -> Room:
        if room_id not in self.rooms:
            self.rooms[room_id] = Room(room_id)
        return self.rooms[room_id]

    async def handle_connection(self, websocket, room_id: str) -> None:
        room = self.get_room(room_id)
        room.clients.add(websocket)
        logger.info("client connected to room=%s (total=%d)", room_id, len(room.clients))
        try:
            # Send initial sync step 1
            if room._ypy:
                import y_py as Y
                state_vec = Y.encode_state_vector(room.ydoc)
                sync_msg = bytes([MSG_SYNC]) + bytes([SYNC_STEP_1]) + _varint_encode(len(state_vec)) + state_vec
                await websocket.send_bytes(sync_msg)

            while True:
                msg = await websocket.receive_bytes()
                await self._handle_message(websocket, room, msg)
        except Exception as e:
            logger.debug("client disconnected: %s", e)
        finally:
            room.clients.discard(websocket)

    async def _handle_message(self, ws, room: Room, msg: bytes) -> None:
        if not msg:
            return
        msg_type = msg[0]
        if msg_type == MSG_SYNC:
            if not room._ypy:
                # Echo to peers
                await room.broadcast(msg, exclude=ws)
                return
            import y_py as Y
            sub_type = msg[1]
            if sub_type == SYNC_STEP_1:
                state_vec, _ = _read_var_uint8_array(msg, 2)
                update = Y.encode_state_as_update(room.ydoc, state_vec)
                reply = bytes([MSG_SYNC, SYNC_STEP_2]) + _varint_encode(len(update)) + update
                await ws.send_bytes(reply)
            elif sub_type in (SYNC_STEP_2, SYNC_UPDATE):
                update, _ = _read_var_uint8_array(msg, 2)
                Y.apply_update(room.ydoc, update)
                # Rebroadcast as SYNC_UPDATE
                update_msg = bytes([MSG_SYNC, SYNC_UPDATE]) + _varint_encode(len(update)) + update
                await room.broadcast(update_msg, exclude=ws)
        elif msg_type == MSG_AWARENESS:
            # Awareness update: just rebroadcast
            await room.broadcast(msg, exclude=ws)
        elif msg_type == MSG_QUERY_AWARENESS:
            # respond with aggregated awareness — simplified
            pass

    def snapshot(self) -> Dict[str, Any]:
        return {
            "host": self.host, "port": self.port,
            "rooms": [
                {"id": r.room_id, "clients": len(r.clients),
                 "awareness": len(r.awareness),
                 "ypy_enabled": r._ypy}
                for r in self.rooms.values()
            ],
        }


_singleton: Optional[YWSServer] = None


def default_yws_server() -> YWSServer:
    global _singleton
    if _singleton is None:
        port = int(os.getenv("LARKMENTOR_SYNC_PORT", "8002"))
        _singleton = YWSServer(port=port)
    return _singleton
