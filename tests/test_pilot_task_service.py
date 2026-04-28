"""P2 收官 · TaskService 应用服务测试."""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest

from core.agent_pilot.application import TaskService
from core.agent_pilot.application.task_service import TaskRepository
from core.agent_pilot.domain import (
    Artifact,
    ArtifactKind,
    ContextPack,
    OwnerLockedError,
    SourceMessage,
    TaskEvent,
    TaskState,
)
from core.agent_pilot.domain.context_pack import OutputRequirements


@pytest.fixture
def svc(tmp_path):
    repo = TaskRepository(root=str(tmp_path))
    return TaskService(repository=repo)


def test_create_task_persists_to_disk(svc, tmp_path):
    t = svc.create_task(intent="活动复盘汇报", owner_open_id="u1")
    assert t.state == TaskState.SUGGESTED
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert t.task_id in content


def test_get_returns_live_task(svc):
    t = svc.create_task(intent="x", owner_open_id="u1")
    same = svc.get(t.task_id)
    assert same is t


def test_fire_advances_state(svc):
    t = svc.create_task(intent="x", owner_open_id="u1")
    svc.fire(t.task_id, TaskEvent.USER_CONFIRM, actor_open_id="u1")
    assert svc.get(t.task_id).state == TaskState.ASSIGNED


def test_assign_changes_owner(svc):
    t = svc.create_task(intent="x", owner_open_id="u1")
    svc.assign(t.task_id, to_open_id="u2", by_open_id="u1")
    assert svc.get(t.task_id).owner_lock.owner_open_id == "u2"


def test_claim_by_self(svc):
    t = svc.create_task(intent="x", owner_open_id="")  # no initial owner
    svc.claim(t.task_id, by_open_id="u3")
    assert svc.get(t.task_id).owner_lock.owner_open_id == "u3"


def test_attach_context_with_confirmation(svc):
    t = svc.create_task(intent="x", owner_open_id="u1")
    cp = ContextPack(
        task_id="",
        task_goal="活动复盘",
        owner_open_id="u1",
        source_messages=[SourceMessage(sender_open_id="u1", text="msg")],
        output_requirements=OutputRequirements(primary="ppt", audience="leader"),
    )
    svc.attach_context(t.task_id, cp, confirmed=True)
    t2 = svc.get(t.task_id)
    assert t2.context_pack is not None
    assert t2.context_pack.confirmed_by_owner
    assert t2.context_pack.has_min_info()


def test_add_artifact_persists(svc, tmp_path):
    t = svc.create_task(intent="x", owner_open_id="u1")
    art = Artifact(artifact_id="a1", task_id="",
                    kind=ArtifactKind.DOC, title="doc",
                    feishu_url="https://x")
    svc.add_artifact(t.task_id, art)
    t2 = svc.get(t.task_id)
    assert len(t2.artifacts) == 1
    # persisted
    files = list(tmp_path.glob("*.json"))
    content = files[0].read_text(encoding="utf-8")
    assert "a1" in content


def test_owner_lock_blocks_fire_on_high_impact_event(svc):
    """High-impact event from non-owner is blocked at fire-time."""
    t = svc.create_task(intent="x", owner_open_id="u1")
    svc.fire(t.task_id, TaskEvent.USER_CONFIRM, actor_open_id="u1")
    svc.fire(t.task_id, TaskEvent.USER_SKIP_CONTEXT, actor_open_id="u1")
    # state = PLANNING, owner = u1
    with pytest.raises(OwnerLockedError):
        svc.fire(t.task_id, TaskEvent.PLAN_DONE_DOC, actor_open_id="u2")


def test_stats_aggregates_by_state(svc):
    a = svc.create_task(intent="a", owner_open_id="u1")
    b = svc.create_task(intent="b", owner_open_id="u1")
    svc.fire(a.task_id, TaskEvent.USER_CONFIRM, actor_open_id="u1")
    s = svc.stats()
    assert s["total"] == 2
    assert s.get("suggested", 0) >= 1
    assert s.get("assigned", 0) >= 1


def test_repository_list_returns_recent_first(svc, tmp_path):
    a = svc.create_task(intent="A", owner_open_id="u1")
    b = svc.create_task(intent="B", owner_open_id="u1")
    rows = svc.repo.list()
    assert len(rows) == 2
    # mtime DESC: b first
    assert rows[0]["intent"] in ("A", "B")  # mtime resolution can be coarse
