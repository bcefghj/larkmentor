"""P9 · PilotLearner 学习闭环测试."""
from __future__ import annotations

import time

import pytest

from core.agent_pilot.application import (
    ContextBuildOptions,
    ContextService,
    PilotLearner,
    PlannerService,
    TaskService,
)
from core.agent_pilot.application.learner import jaccard, tokenize
from core.agent_pilot.application.task_service import TaskRepository
from core.agent_pilot.domain import EventBus, TaskEvent
from core.agent_pilot.domain.events import EVT_TASK_DELIVERED, make_event


@pytest.fixture
def learner(tmp_path):
    return PilotLearner(
        archival_path=str(tmp_path / "archival.jsonl"),
        skills_root=str(tmp_path / "skills"),
        similarity_threshold=0.3,
        min_similar_tasks=3,
    )


def test_tokenize_chinese():
    tk = tokenize("活动复盘汇报")
    # 字 bigram: "活动"/"动复"/"复盘"/"盘汇"/"汇报"
    assert "活动" in tk
    assert "复盘" in tk
    assert "汇报" in tk


def test_tokenize_english():
    tk = tokenize("Quarterly review PPT")
    assert "quarterly" in tk
    assert "review" in tk


def test_jaccard_identical():
    assert jaccard(["a", "b", "c"], ["a", "b", "c"]) == 1.0


def test_jaccard_disjoint():
    assert jaccard(["a", "b"], ["c", "d"]) == 0.0


def test_jaccard_partial():
    # |{a}| / |{a,b,c,d,e}| = 1/5 = 0.2
    assert jaccard(["a", "b", "c"], ["a", "d", "e"]) == pytest.approx(0.2)


# ── 学习与生成 ──────────────────────────────────────────────────────────────


def _make_task(svc, ctx_svc, intent: str, owner: str = "u1"):
    t = svc.create_task(intent=intent, owner_open_id=owner)
    cp = ctx_svc.build(ContextBuildOptions(
        task_id=t.task_id, task_goal=intent, owner_open_id=owner,
        output_primary="ppt", output_audience="leader",
    ))
    t.attach_context(cp, confirmed=True)
    ps = PlannerService(planner_factory=False)
    ps.plan_for_task(t)
    return t


def test_learn_first_task_no_skill_yet(learner, tmp_path):
    svc = TaskService(repository=TaskRepository(root=str(tmp_path / "t1")))
    ctx = ContextService(upload_root=str(tmp_path))
    t = _make_task(svc, ctx, "做活动复盘汇报 PPT")
    learner.learn_from_task(t)
    assert len(learner.list_skills()) == 0  # 第一次没生成


def test_learn_three_similar_tasks_generates_skill(learner, tmp_path):
    svc = TaskService(repository=TaskRepository(root=str(tmp_path / "t1")))
    ctx = ContextService(upload_root=str(tmp_path))
    intents = [
        "做活动复盘汇报 PPT 给老板看",
        "活动复盘汇报 PPT 给老板",
        "活动复盘 PPT 老板汇报",
    ]
    for intent in intents:
        t = _make_task(svc, ctx, intent)
        learner.learn_from_task(t)
    skills = learner.list_skills()
    assert len(skills) >= 1
    sk = skills[0]
    assert sk.intent_pattern  # 持有 pattern
    # SKILL.md 落盘
    from pathlib import Path
    assert Path(sk.md_path).exists()


def test_skill_md_contents(learner, tmp_path):
    svc = TaskService(repository=TaskRepository(root=str(tmp_path / "t1")))
    ctx = ContextService(upload_root=str(tmp_path))
    for i in range(3):
        t = _make_task(svc, ctx, f"季度活动复盘汇报 PPT version{i}")
        learner.learn_from_task(t)
    sk = learner.list_skills()[-1]
    from pathlib import Path
    md = Path(sk.md_path).read_text(encoding="utf-8")
    assert "Auto-generated" in md
    assert sk.skill_id in md
    assert "Plan Template" in md


def test_hit_skill_after_generation(learner, tmp_path):
    svc = TaskService(repository=TaskRepository(root=str(tmp_path / "t1")))
    ctx = ContextService(upload_root=str(tmp_path))
    for i in range(3):
        t = _make_task(svc, ctx, f"做活动复盘汇报 PPT 版本{i}")
        learner.learn_from_task(t)
    # 第 4 次 → 命中
    hit = learner.hit_skill("做活动复盘汇报 PPT 第四次")
    assert hit is not None
    assert hit.hit_count == 1


def test_archival_persisted(tmp_path):
    learner = PilotLearner(
        archival_path=str(tmp_path / "arch.jsonl"),
        skills_root=str(tmp_path / "sk"),
        similarity_threshold=0.3,
        min_similar_tasks=10,  # 阻止生成 skill
    )
    svc = TaskService(repository=TaskRepository(root=str(tmp_path / "ts")))
    ctx = ContextService(upload_root=str(tmp_path))
    t = _make_task(svc, ctx, "活动复盘")
    learner.learn_from_task(t)
    # reload
    learner2 = PilotLearner(
        archival_path=str(tmp_path / "arch.jsonl"),
        skills_root=str(tmp_path / "sk"),
    )
    assert len(learner2._memories) == 1
    assert learner2._memories[0].intent == "活动复盘"


def test_event_bus_subscribe_attaches_to_delivery(tmp_path):
    """attach_to_bus 后，task_delivered 事件触发 learn_from_task."""
    bus = EventBus()
    learner = PilotLearner(
        archival_path=str(tmp_path / "arch.jsonl"),
        skills_root=str(tmp_path / "sk"),
        event_bus=bus,
    )
    learner.attach_to_bus()

    svc = TaskService(
        repository=TaskRepository(root=str(tmp_path / "ts")),
        event_bus=bus,
    )
    # 注入 default_task_service 以便 event 回调能找到 task
    from core.agent_pilot.application.task_service import _default_service
    import core.agent_pilot.application.task_service as ts_mod
    ts_mod._default_service = svc

    ctx = ContextService(upload_root=str(tmp_path))
    t = _make_task(svc, ctx, "做活动复盘")
    # 模拟 deliver 事件
    bus.publish(make_event(EVT_TASK_DELIVERED, t.task_id))
    # 重置 default
    ts_mod._default_service = _default_service
    assert len(learner._memories) == 1


def test_stats(learner, tmp_path):
    svc = TaskService(repository=TaskRepository(root=str(tmp_path / "t1")))
    ctx = ContextService(upload_root=str(tmp_path))
    for i in range(2):
        learner.learn_from_task(_make_task(svc, ctx, f"任务{i}"))
    s = learner.stats()
    assert s["memories"] == 2
    assert s["skills"] == 0


def test_no_skill_when_intents_dissimilar(learner, tmp_path):
    """3 个完全不同主题的任务不应触发 SKILL 生成."""
    svc = TaskService(repository=TaskRepository(root=str(tmp_path / "t1")))
    ctx = ContextService(upload_root=str(tmp_path))
    for intent in ["写产品方案", "画架构图", "做合同总结"]:
        learner.learn_from_task(_make_task(svc, ctx, intent))
    assert len(learner.list_skills()) == 0
