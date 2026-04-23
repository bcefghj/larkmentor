"""Integration tests: boot the FastAPI dashboard with TestClient and
exercise the Agent-Pilot endpoints end-to-end."""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(scope="module")
def client():
    try:
        from fastapi.testclient import TestClient
    except Exception:
        pytest.skip("fastapi TestClient unavailable")
    from dashboard.server import app
    with TestClient(app) as c:
        yield c


def test_pilot_scenarios_endpoint(client):
    resp = client.get("/api/pilot/scenarios")
    assert resp.status_code == 200
    body = resp.json()
    keys = {s["key"] for s in body}
    assert keys == {"A_intent", "B_planner", "C_doc_canvas",
                    "D_slide", "E_sync", "F_delivery"}


def test_pilot_launch_creates_plan(client):
    resp = client.post("/api/pilot/launch",
                       json={"intent": "把本周讨论做成方案 + PPT",
                             "open_id": "ou_api_test"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["plan_id"].startswith("plan_")
    assert body["total_steps"] >= 1


def test_pilot_plan_detail_endpoint(client):
    resp = client.post("/api/pilot/launch",
                       json={"intent": "帮我起草一个产品需求文档", "open_id": "ou_api_test"})
    plan_id = resp.json()["plan_id"]

    # Give background thread a moment
    import time
    time.sleep(0.2)

    detail = client.get(f"/api/pilot/plan/{plan_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["plan_id"] == plan_id
    assert isinstance(body["steps"], list)


def test_pilot_list_filters_by_open_id(client):
    client.post("/api/pilot/launch",
                json={"intent": "demo a", "open_id": "ou_user_a"})
    client.post("/api/pilot/launch",
                json={"intent": "demo b", "open_id": "ou_user_b"})
    resp = client.get("/api/pilot/plans?open_id=ou_user_a&limit=20")
    assert resp.status_code == 200
    body = resp.json()
    assert any(p.get("intent") == "demo a" for p in body)


def test_sync_health_endpoint(client):
    resp = client.get("/sync/health")
    assert resp.status_code == 200
    assert resp.json().get("ok") is True


def test_pilot_share_page_renders(client):
    # Launch a plan first so the share page has something to show
    launch = client.post("/api/pilot/launch",
                         json={"intent": "分享页测试", "open_id": "ou_share_test"})
    plan_id = launch.json()["plan_id"]
    resp = client.get(f"/pilot/{plan_id}")
    assert resp.status_code == 200
    assert plan_id in resp.text
