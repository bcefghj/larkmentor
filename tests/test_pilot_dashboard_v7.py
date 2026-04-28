"""P10 · Dashboard v7 三视角 API 测试 (FastAPI TestClient)."""
from __future__ import annotations

import os

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app(tmp_path):
    """新建一个隔离 FastAPI app，挂 v7 路由（不依赖完整 dashboard.server）."""
    from dashboard.api_v7 import install_v7_routes
    a = FastAPI()
    install_v7_routes(a, static_dir=tmp_path / "v7")
    return a


@pytest.fixture
def client(app):
    return TestClient(app)


# ── API 路由 ───────────────────────────────────────────────────────────────


def test_v7_tasks_list_returns_array(client):
    r = client.get("/api/v7/tasks")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_v7_tasks_list_with_pilot_task(client, tmp_path):
    """实际创建一个任务后，列表里应能看到."""
    # reset task service singleton
    import core.agent_pilot.application.task_service as ts_mod
    from core.agent_pilot.application.task_service import (
        TaskRepository,
        TaskService,
    )
    backup = ts_mod._default_service
    ts_mod._default_service = TaskService(repository=TaskRepository(root=str(tmp_path / "tasks")))
    try:
        from core.agent_pilot.application import default_task_service
        t = default_task_service().create_task(
            intent="测试任务", owner_open_id="u1",
        )
        r = client.get("/api/v7/tasks")
        data = r.json()
        ids = [x["task_id"] for x in data]
        assert t.task_id in ids
    finally:
        ts_mod._default_service = backup


def test_v7_task_detail_404_for_unknown(client):
    r = client.get("/api/v7/tasks/nonexistent")
    assert r.status_code == 404


def test_v7_task_detail_returns_full_object(client, tmp_path):
    import core.agent_pilot.application.task_service as ts_mod
    from core.agent_pilot.application.task_service import (
        TaskRepository,
        TaskService,
    )
    backup = ts_mod._default_service
    ts_mod._default_service = TaskService(repository=TaskRepository(root=str(tmp_path / "tasks")))
    try:
        from core.agent_pilot.application import default_task_service
        t = default_task_service().create_task(intent="x", owner_open_id="u1")
        r = client.get(f"/api/v7/tasks/{t.task_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["task_id"] == t.task_id
        assert data["state"] == "suggested"
    finally:
        ts_mod._default_service = backup


def test_v7_task_timeline(client, tmp_path):
    import core.agent_pilot.application.task_service as ts_mod
    from core.agent_pilot.application.task_service import (
        TaskRepository,
        TaskService,
    )
    backup = ts_mod._default_service
    ts_mod._default_service = TaskService(repository=TaskRepository(root=str(tmp_path / "tasks")))
    try:
        from core.agent_pilot.application import default_task_service
        from core.agent_pilot.domain import TaskEvent
        svc = default_task_service()
        t = svc.create_task(intent="x", owner_open_id="u1")
        svc.fire(t.task_id, TaskEvent.USER_CONFIRM, actor_open_id="u1")
        r = client.get(f"/api/v7/tasks/{t.task_id}/timeline")
        assert r.status_code == 200
        data = r.json()
        assert len(data["transitions"]) == 1
        assert data["transitions"][0]["event"] == "user_confirm"
    finally:
        ts_mod._default_service = backup


def test_v7_skills_returns_array(client):
    r = client.get("/api/v7/skills")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_v7_triad_returns_three_lines(client):
    r = client.get("/api/v7/triad")
    assert r.status_code == 200
    data = r.json()
    assert "shield" in data
    assert "mentor" in data
    assert "pilot" in data
    assert "label" in data["shield"]


def test_v7_intent_stats_returns_thresholds(client):
    r = client.get("/api/v7/intent_stats")
    assert r.status_code == 200
    data = r.json()
    assert "fired_count" in data
    assert "rule_threshold" in data


def test_v7_memory_returns_tier_structure(client):
    r = client.get("/api/v7/memory?tenant=default")
    assert r.status_code == 200
    data = r.json()
    assert "tenant" in data
    assert "tiers" in data
    assert isinstance(data["tiers"], list)


# ── HTML 视图 ─────────────────────────────────────────────────────────────


def test_v7_pilot_html_renders(client):
    r = client.get("/v7/pilot")
    assert r.status_code == 200
    assert b"Agent-Pilot" in r.content
    # 验证基本路由按钮存在
    assert b"\xe4\xbb\xbb\xe5\x8a\xa1\xe5\x88\x97\xe8\xa1\xa8" in r.content  # 「任务列表」


def test_v7_memory_html_renders(client):
    r = client.get("/v7/memory")
    assert r.status_code == 200
    assert b"Memory" in r.content


def test_v7_triad_html_renders(client):
    r = client.get("/v7/triad")
    assert r.status_code == 200
    assert b"\xe4\xb8\x89\xe7\xba\xbf" in r.content  # 「三线」
