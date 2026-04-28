"""Tests for the CRDT sync hub and Orchestrator bridge."""

from __future__ import annotations

import pytest

from core.sync.crdt_hub import CrdtHub, broadcast_event, broadcast_state, default_hub
from core.sync import offline_merge


# ─────────────────────────── Basic pub/sub ───────────────────────

def test_subscribe_and_fanout_to_single_client():
    hub = CrdtHub()
    received = []
    hub.subscribe("c1", received.append)
    hub.join("c1", "plan_xyz")
    hub.publish_event("plan_xyz", {"kind": "plan_started"})
    assert len(received) == 1
    assert received[0]["kind"] == "event"
    assert received[0]["event"]["kind"] == "plan_started"


def test_fanout_respects_room_scope():
    hub = CrdtHub()
    a, b, c = [], [], []
    hub.subscribe("ca", a.append)
    hub.subscribe("cb", b.append)
    hub.subscribe("cc", c.append)
    hub.join("ca", "room_a")
    hub.join("cb", "room_a")
    hub.join("cc", "room_b")
    hub.publish_state("room_a", {"hello": 1})
    assert len(a) == 1
    assert len(b) == 1
    assert len(c) == 0


def test_history_replay_on_join():
    hub = CrdtHub(history_size=10)
    hub.publish_event("room_1", {"kind": "step_done"})
    hub.publish_event("room_1", {"kind": "step_done"})
    received = []
    hub.subscribe("client", received.append)
    history = hub.join("client", "room_1")
    assert len(history) == 2
    assert all(h["kind"] == "event" for h in history)


def test_unsubscribe_removes_from_all_rooms():
    hub = CrdtHub()
    recv = []
    hub.subscribe("cx", recv.append)
    hub.join("cx", "r1")
    hub.join("cx", "r2")
    hub.unsubscribe("cx")
    hub.publish_event("r1", {"kind": "x"})
    hub.publish_event("r2", {"kind": "y"})
    assert recv == []


# ─────────────────────────── Broadcaster helpers ───────────────

def test_broadcast_state_uses_default_hub():
    recv = []
    default_hub().subscribe("mod_test", recv.append)
    default_hub().join("mod_test", "plan_mod")
    broadcast_state("plan_mod", {"ok": True})
    broadcast_event("plan_mod", {"kind": "step_done"})
    kinds = [r["kind"] for r in recv]
    assert "state" in kinds and "event" in kinds
    default_hub().unsubscribe("mod_test")


# ─────────────────────────── Offline merge log ───────────────

def test_offline_merge_logs_updates(tmp_path, monkeypatch):
    monkeypatch.setattr(offline_merge, "DATA_DIR", str(tmp_path))
    offline_merge.record_offline_update("room_offline", "AAA", client_id="ipad_1")
    offline_merge.record_offline_update("room_offline", "BBB", client_id="mac_1")
    summary = offline_merge.reconcile("room_offline")
    assert summary["offline_updates"] == 2
    assert summary["by_client"] == {"ipad_1": 1, "mac_1": 1}
