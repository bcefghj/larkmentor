"""P8 · PilotRouter 端到端 IM 主流程测试.

模拟从 IM 文本消息 → 三闸门 → 任务卡 → 按钮回调 → 状态机推进的完整链路,
不联通飞书。
"""
from __future__ import annotations

import json

import pytest

from bot.pilot_router import PilotRouter, RouterResult
from core.agent_pilot.application import (
    ContextService,
    IntentDetector,
    IntentDetectorConfig,
    PlannerService,
    TaskService,
)
from core.agent_pilot.application.task_service import TaskRepository
from core.agent_pilot.domain import TaskState


def _mock_llm_yes(text: str) -> str:
    return json.dumps({
        "is_task": True, "task_type": "ppt",
        "goal": "活动复盘汇报", "resources": ["数据"],
        "next_step": "确认", "confidence": 0.88,
    })


def _mock_llm_no(text: str) -> str:
    return json.dumps({
        "is_task": False, "goal": "", "confidence": 0.1,
    })


@pytest.fixture
def router(tmp_path):
    sent_cards = []

    def sender(target, card, *, scope):
        sent_cards.append((target, card, scope))
        return "msg-1"

    r = PilotRouter(
        task_service=TaskService(repository=TaskRepository(root=str(tmp_path))),
        intent_detector=IntentDetector(llm_caller=_mock_llm_yes),
        context_service=ContextService(upload_root=str(tmp_path)),
        planner_service=PlannerService(planner_factory=False),
        card_sender=sender,
    )
    r._sent_cards = sent_cards  # 测试访问
    return r


# ── 主流程：READY 路径 ────────────────────────────────────────────────────


def test_router_creates_task_card_on_ready(router):
    res = router.handle_chat_message(
        sender_open_id="u1",
        text="下周做活动复盘汇报给老板看",
        chat_id="g1",
    )
    assert res.handled
    assert res.verdict == "ready"
    assert res.task_id
    assert res.card is not None
    # 卡片已发送
    assert len(router._sent_cards) == 1
    target, card, scope = router._sent_cards[0]
    assert target == "g1"
    assert scope == "chat"
    assert card["schema"] == "2.0"


def test_router_silent_on_not_intent(router):
    """无关键词 → 直接 silent."""
    router.intent_detector.llm_caller = _mock_llm_no
    res = router.handle_chat_message(
        sender_open_id="u1", text="今天天气不错", chat_id="g1",
    )
    assert res.handled
    assert res.verdict == "not_intent"
    assert res.task_id == ""
    assert len(router._sent_cards) == 0


def test_router_skips_when_in_focus_mode(router):
    res = router.handle_chat_message(
        sender_open_id="u1", text="下周做活动复盘汇报",
        chat_id="g1", in_focus_mode=True,
    )
    assert not res.handled
    assert res.verdict == "focus_mode_bypass"


def test_router_handles_explicit_pilot_command(router):
    res = router.handle_chat_message(
        sender_open_id="u1",
        text="/pilot 把上周讨论整理成 8 页汇报 PPT",
        chat_id="g1",
    )
    assert res.handled
    assert res.verdict == "explicit_ready"
    assert res.task_id


def test_router_cooldown_blocks_repeat(router):
    res1 = router.handle_chat_message(
        sender_open_id="u1", text="下周做活动复盘汇报", chat_id="g1",
    )
    assert res1.verdict == "ready"
    res2 = router.handle_chat_message(
        sender_open_id="u1", text="下周做活动复盘汇报", chat_id="g1",
    )
    assert res2.verdict == "cooldown"
    assert len(router._sent_cards) == 1  # 第二次不弹卡


def test_router_clarify_when_lowconf(tmp_path):
    """低置信度 → 弹 clarify card."""
    def lowconf(text):
        return json.dumps({"is_task": True, "goal": "x", "confidence": 0.30})

    sent = []

    r = PilotRouter(
        task_service=TaskService(repository=TaskRepository(root=str(tmp_path))),
        intent_detector=IntentDetector(llm_caller=lowconf),
        context_service=ContextService(upload_root=str(tmp_path)),
        planner_service=PlannerService(planner_factory=False),
        card_sender=lambda t, c, *, scope: sent.append((t, c, scope)) or "ok",
    )
    res = r.handle_chat_message(
        sender_open_id="u1", text="下周做汇报", chat_id="g1",
    )
    assert res.verdict == "clarify"
    # clarify card 包含至少 1 个 PRD §5 模板澄清问题
    s = json.dumps(sent[0][1], ensure_ascii=False)
    assert any(k in s for k in ("文档、PPT", "已有资料", "汇报对象"))


# ── 主流程：按钮回调 ──────────────────────────────────────────────────────


def test_router_action_confirm_advances_state(router):
    res1 = router.handle_chat_message(
        sender_open_id="u1", text="下周做活动复盘汇报", chat_id="g1",
    )
    task_id = res1.task_id

    res2 = router.handle_card_action(
        actor_open_id="u1",
        action="pilot.task.confirm",
        value={"task_id": task_id},
    )
    assert res2.handled
    assert res2.verdict == "confirmed"
    task = router.task_service.get(task_id)
    assert task.state == TaskState.ASSIGNED


def test_router_action_ignore_marks_cooldown(router):
    res1 = router.handle_chat_message(
        sender_open_id="u1", text="下周做活动复盘汇报", chat_id="g1",
    )
    res2 = router.handle_card_action(
        actor_open_id="u1",
        action="pilot.task.ignore",
        value={"task_id": res1.task_id},
    )
    assert res2.verdict == "ignored"
    task = router.task_service.get(res1.task_id)
    assert task.state == TaskState.IGNORED


def test_router_action_assign_to_changes_owner(router):
    res1 = router.handle_chat_message(
        sender_open_id="u1", text="下周做活动复盘汇报", chat_id="g1",
    )
    res = router.handle_card_action(
        actor_open_id="u1",
        action="pilot.task.assign_to",
        value={"task_id": res1.task_id, "to_open_id": "u2"},
    )
    assert res.verdict == "assigned"
    task = router.task_service.get(res1.task_id)
    assert task.owner_lock.owner_open_id == "u2"


def test_router_action_claim_self_no_owner_initially(tmp_path):
    sent = []

    r = PilotRouter(
        task_service=TaskService(repository=TaskRepository(root=str(tmp_path))),
        intent_detector=IntentDetector(llm_caller=_mock_llm_yes),
        context_service=ContextService(upload_root=str(tmp_path)),
        planner_service=PlannerService(planner_factory=False),
        card_sender=lambda *a, **k: sent.append(a) or "ok",
    )
    res1 = r.handle_chat_message(
        sender_open_id="u1", text="下周做活动复盘汇报", chat_id="g1",
    )
    res2 = r.handle_card_action(
        actor_open_id="u3",
        action="pilot.task.claim_self",
        value={"task_id": res1.task_id},
    )
    assert res2.verdict == "claimed"
    task = r.task_service.get(res1.task_id)
    assert task.owner_lock.owner_open_id == "u3"


def test_router_action_confirm_context_runs_planner(router):
    res1 = router.handle_chat_message(
        sender_open_id="u1", text="下周做活动复盘汇报给老板", chat_id="g1",
    )
    router.handle_card_action(
        actor_open_id="u1", action="pilot.task.confirm",
        value={"task_id": res1.task_id},
    )
    res = router.handle_card_action(
        actor_open_id="u1", action="pilot.ctx.confirm",
        value={"task_id": res1.task_id},
    )
    assert res.verdict == "ctx_confirmed"
    task = router.task_service.get(res1.task_id)
    assert task.plan is not None
    # state advanced past PLANNING (orchestrator not yet invoked) so still PLANNING
    assert task.state == TaskState.PLANNING


def test_router_unknown_action_returns_error(router):
    res = router.handle_card_action(
        actor_open_id="u1", action="pilot.task.unknown",
        value={"task_id": "x"},
    )
    assert not res.handled
    assert "unknown_action" in res.error


def test_router_pause_action(router):
    res1 = router.handle_chat_message(
        sender_open_id="u1", text="下周做活动复盘汇报", chat_id="g1",
    )
    router.handle_card_action(
        actor_open_id="u1", action="pilot.task.confirm",
        value={"task_id": res1.task_id},
    )
    res = router.handle_card_action(
        actor_open_id="u1", action="pilot.task.pause",
        value={"task_id": res1.task_id},
    )
    assert res.verdict == "paused"
    task = router.task_service.get(res1.task_id)
    assert task.state == TaskState.PAUSED
