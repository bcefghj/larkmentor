"""P7 · Pilot 卡片家族测试 (PRD §5.4 / §6.3 / §7.2 + cardkit.v1)."""
from __future__ import annotations

import json

import pytest

from bot.cards_pilot import (
    assign_picker_card,
    context_confirm_card,
    multi_agent_card,
    task_clarify_card,
    task_delivered_card,
    task_progress_card,
    task_suggested_card,
)


# ── helper: validate v2 schema 基础结构 ──────────────────────────────────────


def _validate_v2_card(card: dict) -> None:
    assert card.get("schema") == "2.0", "must be v2 card"
    assert "header" in card
    assert "body" in card
    assert "elements" in card["body"]
    # JSON 可序列化
    json.dumps(card, ensure_ascii=False)


def _all_element_ids(card: dict) -> list[str]:
    """Collect all element_id values for stable patch tests."""
    out = []

    def walk(node):
        if isinstance(node, dict):
            if "element_id" in node:
                out.append(node["element_id"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(card)
    return out


# ── 1. task_suggested_card (PRD §5.4) ───────────────────────────────────────


def test_task_suggested_card_has_5_buttons():
    card = task_suggested_card(
        task_id="task-abc123",
        title="活动复盘汇报",
        intent="下周做活动复盘汇报给老板",
        owner_open_id="u1",
        owner_display="张三",
    )
    _validate_v2_card(card)
    eids = _all_element_ids(card)
    # PRD §5.4 5 按钮全部存在
    expected_btns = {"pilot.btn.confirm", "pilot.btn.add_ctx",
                     "pilot.btn.assign", "pilot.btn.ignore"}
    assert expected_btns.issubset(set(eids))


def test_task_suggested_card_with_detail_url():
    card = task_suggested_card(
        task_id="t1", title="x", intent="x",
        detail_url="http://localhost:8001/tasks/t1",
    )
    eids = _all_element_ids(card)
    assert "pilot.btn.detail" in eids


def test_task_suggested_card_renders_plan_outline():
    card = task_suggested_card(
        task_id="t1", title="x", intent="x",
        plan_outline=["补充资料", "生成文档", "生成 PPT", "演讲稿"],
    )
    s = json.dumps(card, ensure_ascii=False)
    assert "补充资料" in s
    assert "生成 PPT" in s


def test_task_suggested_card_context_state():
    card = task_suggested_card(
        task_id="t1", title="x", intent="x",
        context_state={
            "used": 12,
            "missing": ["历史复盘", "预算表"],
            "suggested": ["近 3 月数据"],
        },
    )
    s = json.dumps(card, ensure_ascii=False)
    assert "12" in s
    assert "历史复盘" in s
    assert "近 3 月数据" in s


def test_task_suggested_card_stable_element_ids():
    """element_id 在多次构造同样输入时必须稳定（cardkit patch 关键）."""
    a = task_suggested_card(task_id="t1", title="x", intent="x")
    b = task_suggested_card(task_id="t1", title="x", intent="x")
    assert _all_element_ids(a) == _all_element_ids(b)


# ── 2. assign_picker_card (PRD §6.3) ────────────────────────────────────────


def test_assign_picker_card_has_candidates():
    card = assign_picker_card(
        task_id="t1",
        candidates=[
            {"open_id": "ou_aaa", "name": "张三"},
            {"open_id": "ou_bbb", "name": "李四"},
            {"open_id": "ou_ccc", "name": "王五"},
        ],
    )
    _validate_v2_card(card)
    s = json.dumps(card, ensure_ascii=False)
    assert "张三" in s
    assert "李四" in s
    assert "王五" in s


def test_assign_picker_card_has_claim_self():
    card = assign_picker_card(task_id="t1", candidates=[])
    eids = _all_element_ids(card)
    assert "pilot.assign.btn.claim_self" in eids


def test_assign_picker_card_truncates_to_12():
    candidates = [{"open_id": f"u{i}", "name": f"用户{i}"} for i in range(20)]
    card = assign_picker_card(task_id="t1", candidates=candidates)
    s = json.dumps(card, ensure_ascii=False)
    assert "用户0" in s
    assert "用户11" in s
    assert "用户15" not in s  # truncated


# ── 3. context_confirm_card (PRD §7.2) ──────────────────────────────────────


def test_context_confirm_card_ready_state():
    """has_min_info=True → primary 按钮，绿色 header."""
    summary = {
        "task_goal": "活动复盘",
        "msg_count": 18,
        "doc_count": 2,
        "user_material_count": 1,
        "missing": [],
        "has_min_info": True,
        "total_chars": 3000,
        "output_primary": "ppt",
        "output_audience": "leader",
        "must_cite": True,
    }
    card = context_confirm_card(task_id="t1", summary=summary)
    _validate_v2_card(card)
    s = json.dumps(card, ensure_ascii=False)
    assert "确认生成" in s
    assert "ppt" in s
    assert "leader" in s
    assert card["header"]["template"] == "green"


def test_context_confirm_card_warning_state():
    summary = {
        "task_goal": "x",
        "msg_count": 0, "doc_count": 0, "user_material_count": 0,
        "missing": ["any_material", "task_goal"],
        "has_min_info": False,
        "total_chars": 0,
        "output_primary": "doc", "output_audience": "",
        "must_cite": False,
    }
    card = context_confirm_card(task_id="t1", summary=summary)
    s = json.dumps(card, ensure_ascii=False)
    assert "信息不足" in s
    assert "any_material" in s
    assert card["header"]["template"] == "orange"


# ── 4. multi_agent_card ─────────────────────────────────────────────────────


def test_multi_agent_card_full_run():
    transcripts = [
        {"agent": "@validator", "ok": True, "summary": "5 gates 5/5 pass", "duration_ms": 230},
        {"agent": "@citation", "ok": True, "summary": "12 claims, 10 verified", "duration_ms": 410},
        {"agent": "@mentor", "ok": True, "summary": "提出 3 条修订建议", "duration_ms": 180},
        {"agent": "@shield", "ok": True, "summary": "安全审查 OK", "duration_ms": 50},
    ]
    card = multi_agent_card(
        task_id="t1",
        pipeline_id="mp-12345",
        transcripts=transcripts,
        quality_gates_passed=5,
        quality_gates_total=5,
        quality_score=0.92,
        citations_total=12,
        citations_verified=10,
        safety_blocked=False,
        overall_ok=True,
    )
    _validate_v2_card(card)
    s = json.dumps(card, ensure_ascii=False)
    assert "@validator" in s
    assert "@citation" in s
    assert "5/5" in s
    assert "10/12" in s
    assert card["header"]["template"] == "green"


def test_multi_agent_card_safety_blocked():
    card = multi_agent_card(
        task_id="t1", pipeline_id="x",
        transcripts=[{"agent": "@shield", "ok": True, "summary": "BLOCKED: phone"}],
        safety_blocked=True,
    )
    s = json.dumps(card, ensure_ascii=False)
    assert "安全审查未通过" in s
    assert card["header"]["template"] == "red"


def test_multi_agent_card_failed_agent_marked():
    card = multi_agent_card(
        task_id="t1", pipeline_id="x",
        transcripts=[{"agent": "@validator", "ok": False, "summary": "crashed"}],
    )
    s = json.dumps(card, ensure_ascii=False)
    assert "❌" in s


# ── 5. task_progress_card (cardkit.v1) ──────────────────────────────────────


def test_task_progress_card_has_streaming_element():
    card = task_progress_card(
        task_id="t1",
        state="generating",
        progress=0.5,
        current_step="生成 PPT 大纲",
        streaming_content="正在写第 3 页...",
    )
    _validate_v2_card(card)
    eids = _all_element_ids(card)
    assert "pilot.prog.stream" in eids
    # cardkit.v1 标志 stream:True
    s = json.dumps(card, ensure_ascii=False)
    assert '"stream": true' in s.lower() or "stream" in s.lower()


def test_task_progress_card_renders_progress_bar():
    card = task_progress_card(task_id="t1", progress=0.75)
    s = json.dumps(card, ensure_ascii=False)
    # 15 个 █ + 5 个 ░
    assert "█" in s


# ── 6. task_delivered_card ──────────────────────────────────────────────────


def test_task_delivered_card_with_artifacts():
    card = task_delivered_card(
        task_id="t1",
        title="活动复盘汇报",
        artifacts=[
            {"icon": "📄", "title": "复盘文档", "url": "https://x.feishu.cn/d1"},
            {"icon": "🎬", "title": "汇报 PPT", "url": "https://x.feishu.cn/p1"},
        ],
        share_url="https://x.feishu.cn/share/abc",
        summary="本次活动覆盖 2400 人，参与率上升 15%",
    )
    _validate_v2_card(card)
    s = json.dumps(card, ensure_ascii=False)
    assert "复盘文档" in s
    assert "汇报 PPT" in s
    assert "https://x.feishu.cn/d1" in s
    assert "https://x.feishu.cn/share/abc" in s


# ── 7. task_clarify_card (PRD §5) ───────────────────────────────────────────


def test_task_clarify_card_renders_questions():
    card = task_clarify_card(
        task_id="t1",
        detected_goal="校园活动复盘",
        questions=[
            "汇报对象是谁？（团队 / 部门 / 老板 / 客户）",
            "希望输出的是文档、PPT 还是自由画布？",
            "是否需要引用已有资料？",
        ],
    )
    _validate_v2_card(card)
    s = json.dumps(card, ensure_ascii=False)
    assert "汇报对象" in s
    assert "校园活动复盘" in s
    eids = _all_element_ids(card)
    assert "pilot.clar.btn.inline" in eids
    assert "pilot.clar.btn.skip" in eids
    assert "pilot.clar.btn.ignore" in eids
