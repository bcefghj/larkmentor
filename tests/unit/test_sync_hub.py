"""Sync Hub 测试 — 多端 join/leave/publish + 离线 reconcile."""

from __future__ import annotations

import asyncio

import pytest


class FakeWS:
    """假 WebSocket，用于单元测试."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False

    async def send_text(self, text: str) -> None:
        if self.closed:
            raise RuntimeError("closed")
        self.sent.append(text)


@pytest.mark.asyncio
async def test_hub_join_and_history():
    from pilot.surface.sync.hub import SyncHub

    hub = SyncHub()
    ws = FakeWS()
    cid = await hub.join(room_id="r1", ws=ws)
    assert cid
    assert any("room.joined" in s for s in ws.sent)


@pytest.mark.asyncio
async def test_hub_publish_broadcasts_to_others():
    from pilot.surface.sync.hub import SyncHub

    hub = SyncHub()
    ws_a = FakeWS()
    ws_b = FakeWS()
    cid_a = await hub.join(room_id="r1", ws=ws_a)
    cid_b = await hub.join(room_id="r1", ws=ws_b)

    # B join 时 A 应收到 presence.join
    assert any("presence.join" in s for s in ws_a.sent)

    # A publish 一条事件
    await hub.publish(room_id="r1", kind="step.done", payload={"tool": "doc.create"}, from_client_id=cid_a)
    # B 应收到该事件
    assert any("step.done" in s for s in ws_b.sent)


@pytest.mark.asyncio
async def test_hub_state_set_persists():
    from pilot.surface.sync.hub import SyncHub

    hub = SyncHub()
    await hub.publish(room_id="r2", kind="state.set", payload={"key": "progress", "value": 0.5})
    stats = hub.stats()
    assert stats["rooms_count"] == 1


@pytest.mark.asyncio
async def test_hub_leave_broadcasts_presence():
    from pilot.surface.sync.hub import SyncHub

    hub = SyncHub()
    ws_a = FakeWS()
    ws_b = FakeWS()
    cid_a = await hub.join(room_id="r3", ws=ws_a)
    cid_b = await hub.join(room_id="r3", ws=ws_b)
    await hub.leave(room_id="r3", client_id=cid_a)
    assert any("presence.leave" in s for s in ws_b.sent)


@pytest.mark.asyncio
async def test_hub_history_replay_to_late_joiner():
    """晚加入的 client 应该收到 history（PRD §F-15 离线合并基础）."""
    from pilot.surface.sync.hub import SyncHub

    hub = SyncHub()
    ws_a = FakeWS()
    cid_a = await hub.join(room_id="r4", ws=ws_a)
    await hub.publish(room_id="r4", kind="step.done", payload={"x": 1}, from_client_id=cid_a)
    await hub.publish(room_id="r4", kind="step.done", payload={"x": 2}, from_client_id=cid_a)

    # B 晚加入
    ws_b = FakeWS()
    await hub.join(room_id="r4", ws=ws_b)
    # B 第一条 message 应是 room.joined，且 history 含两条事件
    import json
    joined = json.loads(ws_b.sent[0])
    assert joined["kind"] == "room.joined"
    assert len(joined["history"]) == 2
