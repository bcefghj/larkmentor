"""Tests for step8 concurrency improvements:
- user_state._atomic_write: fcntl + atomic rename
- knowledge_base WAL mode + busy_timeout
"""

from __future__ import annotations

import json
import os
import threading
import time

import pytest


def test_atomic_write_writes_and_replaces(tmp_path):
    from memory.user_state import _atomic_write

    target = tmp_path / "out.json"
    payload = {"hello": "world", "n": 3}

    with _atomic_write(str(target)) as f:
        json.dump(payload, f, ensure_ascii=False)

    assert target.exists()
    assert json.loads(target.read_text("utf-8")) == payload


def test_atomic_write_cleans_up_tmp(tmp_path):
    from memory.user_state import _atomic_write

    target = tmp_path / "out.json"
    with _atomic_write(str(target)) as f:
        json.dump({"a": 1}, f)

    leftovers = list(tmp_path.glob("out.json.tmp*"))
    assert leftovers == []


def test_atomic_write_concurrent_writes_no_corruption(tmp_path):
    """Spawn 8 threads writing different payloads; final file must be valid JSON."""
    from memory.user_state import _atomic_write

    target = tmp_path / "concurrent.json"

    def writer(idx: int):
        for _ in range(5):
            payload = {"writer": idx, "ts": time.time()}
            with _atomic_write(str(target)) as f:
                json.dump(payload, f)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert target.exists()
    data = json.loads(target.read_text("utf-8"))
    assert "writer" in data
    assert isinstance(data["writer"], int)


def test_save_all_uses_atomic_write(tmp_path, monkeypatch):
    """Calling _save_all must produce a complete, parseable JSON."""
    from memory import user_state

    state_path = tmp_path / "states.json"
    monkeypatch.setattr(user_state, "STATE_FILE", str(state_path))
    user_state._store.clear()
    u = user_state.get_user("test_open_id")
    u.work_context = "writing report"
    user_state._save_all()
    assert state_path.exists()
    data = json.loads(state_path.read_text("utf-8"))
    assert "test_open_id" in data
    assert data["test_open_id"]["work_context"] == "writing report"


def test_knowledge_base_wal_mode_enabled():
    """Verify the kb sqlite connection has WAL pragma applied."""
    from core.mentor.knowledge_base import _connect

    conn = _connect()
    try:
        cur = conn.execute("PRAGMA journal_mode")
        mode = cur.fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal"


def test_knowledge_base_busy_timeout_set():
    from core.mentor.knowledge_base import _connect

    conn = _connect()
    try:
        cur = conn.execute("PRAGMA busy_timeout")
        timeout_ms = cur.fetchone()[0]
    finally:
        conn.close()
    assert timeout_ms >= 1000
