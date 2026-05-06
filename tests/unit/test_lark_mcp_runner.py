"""Phase 2.1 — 反向 MCP server (lark_mcp_runner) 单测.

只验证：
  1. tools/list 只暴露白名单工具
  2. tools/call 拒绝白名单外的工具（防止评委 client 误调 archive.bundle）
  3. /messages tools/call 正常路径
  4. /health
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _llm_mock(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "1")


def _client():
    from fastapi.testclient import TestClient

    from pilot.surface.lark_mcp_runner import create_app

    return TestClient(create_app())


def test_health():
    r = _client().get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_index_lists_exposed_tools():
    r = _client().get("/")
    body = r.json()
    assert r.status_code == 200
    exposed = set(body["exposed_tools"])
    assert {"doc.create", "doc.append", "slide.generate", "web.search"} <= exposed


def test_tools_list_only_whitelist():
    r = _client().get("/tools/list")
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["tools"]}
    assert names <= {"doc.create", "doc.append", "slide.generate", "web.search"}
    assert "archive.bundle" not in names
    assert "slide.rehearse" not in names


def test_tools_call_rejects_non_whitelist():
    r = _client().post(
        "/tools/call",
        json={"name": "archive.bundle", "arguments": {}},
    )
    assert r.status_code == 400
    assert r.json()["isError"] is True


def test_messages_jsonrpc_unknown_method():
    r = _client().post("/messages", json={"jsonrpc": "2.0", "id": 1, "method": "foo/bar"})
    assert r.status_code == 200
    body = r.json()
    assert body["error"]["code"] == -32601


def test_messages_tools_list_returns_whitelist():
    r = _client().post(
        "/messages",
        json={"jsonrpc": "2.0", "id": 7, "method": "tools/list"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 7
    names = {t["name"] for t in body["result"]["tools"]}
    assert names <= {"doc.create", "doc.append", "slide.generate", "web.search"}
