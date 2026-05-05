"""Tests for dashboard split routes (health, pilot, core endpoints)."""

import os
from unittest.mock import patch

import pytest

try:
    from fastapi.testclient import TestClient
except ImportError:
    pytest.skip("fastapi not installed", allow_module_level=True)

os.environ.setdefault("FEISHU_APP_ID", "test_app_id")
os.environ.setdefault("FEISHU_APP_SECRET", "test_app_secret")
os.environ.pop("AGENT_PILOT_API_KEY", None)

import config as _cfg
if not hasattr(_cfg.Config, "VERSION"):
    _cfg.Settings.VERSION = _cfg.VERSION

from dashboard.server import app, DEMO_MODE
import dashboard.server as srv


@pytest.fixture
def client():
    """TestClient with API key middleware disabled."""
    with patch.dict(os.environ, {"AGENT_PILOT_API_KEY": ""}, clear=False):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


@pytest.fixture(autouse=True)
def _restore_demo_mode():
    """Ensure DEMO_MODE is reset after each test."""
    original = srv.DEMO_MODE
    yield
    srv.DEMO_MODE = original


# ---------------------------------------------------------------------------
# /health – version check
# ---------------------------------------------------------------------------

def test_health_returns_version(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "12.0.0"
    assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# /ready – checks dict
# ---------------------------------------------------------------------------

def test_ready_returns_checks(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert "checks" in data
    assert "llm_configured" in data["checks"]
    assert "feishu_configured" in data["checks"]
    assert isinstance(data["ready"], bool)


# ---------------------------------------------------------------------------
# /api/overview – demo data
# ---------------------------------------------------------------------------

def test_overview_demo_mode(client):
    """In demo mode, /api/overview should return demo data with mode='demo'."""
    srv.DEMO_MODE = True
    resp = client.get("/api/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "demo"
    assert "decisions_today" in data


# ---------------------------------------------------------------------------
# /demo and /live – mode switching
# ---------------------------------------------------------------------------

def test_demo_endpoint_switches_mode(client):
    srv.DEMO_MODE = False
    resp = client.get("/demo")
    assert resp.status_code == 200
    assert resp.json()["mode"] == "demo"
    assert srv.DEMO_MODE is True


def test_live_endpoint_switches_back(client):
    srv.DEMO_MODE = True
    resp = client.get("/live")
    assert resp.status_code == 200
    assert resp.json()["mode"] == "live"
    assert srv.DEMO_MODE is False


# ---------------------------------------------------------------------------
# /api/decisions – list
# ---------------------------------------------------------------------------

def test_decisions_returns_list(client):
    srv.DEMO_MODE = True
    resp = client.get("/api/decisions?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) <= 5


# ---------------------------------------------------------------------------
# /api/heatmap – grid
# ---------------------------------------------------------------------------

def test_heatmap_returns_grid(client):
    srv.DEMO_MODE = True
    resp = client.get("/api/heatmap")
    assert resp.status_code == 200
    data = resp.json()
    assert "grid" in data
    grid = data["grid"]
    assert len(grid) == 7
    assert len(grid[0]) == 24


# ---------------------------------------------------------------------------
# /api/v1/version – features include "streaming"
# ---------------------------------------------------------------------------

def test_version_includes_streaming(client):
    resp = client.get("/api/v1/version")
    assert resp.status_code == 200
    data = resp.json()
    assert "streaming" in data["features"]
    assert data["name"] == "Agent-Pilot"
    assert data["version"] == "12.0.0"


# ---------------------------------------------------------------------------
# CORS – credentials not set to True when origins=*
# ---------------------------------------------------------------------------

def test_cors_no_credentials_when_wildcard():
    """When CORS_ORIGINS='*', allow_credentials should be False."""
    from dashboard.server import _cors_origins
    if "*" in _cors_origins:
        resp = TestClient(app).options(
            "/api/overview",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        cred_header = resp.headers.get("access-control-allow-credentials", "")
        assert cred_header.lower() != "true"


# ---------------------------------------------------------------------------
# Pilot routes mounted (no 404)
# ---------------------------------------------------------------------------

def test_pilot_plans_not_404(client):
    """/api/pilot/plans should be routed (not 404), even if it errors."""
    resp = client.get("/api/pilot/plans")
    assert resp.status_code != 404


def test_pilot_context_not_404(client):
    """/api/pilot/context should be routed (not 404)."""
    resp = client.get("/api/pilot/context")
    assert resp.status_code != 404


# ---------------------------------------------------------------------------
# Additional: /api/profiles, /api/users
# ---------------------------------------------------------------------------

def test_profiles_returns_list(client):
    srv.DEMO_MODE = True
    resp = client.get("/api/profiles?limit=3")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_users_returns_list(client):
    srv.DEMO_MODE = True
    resp = client.get("/api/users")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
