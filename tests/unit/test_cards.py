"""V1.5 — 卡片构造器回归（task_delivered 过滤空 URL + context_confirm 3 按钮）."""

from __future__ import annotations

import json

from pilot.surface.feishu.cards import (
    ContextSummary,
    build_context_confirm_card,
    context_confirm_card,
    task_delivered_card,
)


def _walk_text(card: dict) -> str:
    return json.dumps(card, ensure_ascii=False)


def test_task_delivered_skips_empty_url() -> None:
    card = task_delivered_card(
        task_id="task_x",
        title="测试",
        artifacts=[
            {"kind": "doc", "title": "正常文档", "url": "https://feishu.cn/docx/abc"},
            {"kind": "slide", "title": "空 URL 应该跳过", "url": ""},
            {"kind": "canvas", "title": "也跳过", "url": "  "},
        ],
    )
    text = _walk_text(card)
    assert "正常文档" in text
    assert "空 URL 应该跳过" not in text
    assert "也跳过" not in text
    # 不应该出现空链接的渲染
    assert "[]()" not in text
    assert "[打开]()" not in text


def test_task_delivered_all_empty_shows_placeholder() -> None:
    card = task_delivered_card(task_id="t", title="x", artifacts=[
        {"kind": "doc", "url": ""},
    ])
    assert "产物列表暂时为空" in _walk_text(card)


def test_context_confirm_card_has_three_actions() -> None:
    card = context_confirm_card(
        task_id="task_a",
        summary={"task_summary": "Q4 OKR 汇报", "used": ["doc1"], "missing": ["audience", "time"]},
    )
    text = _walk_text(card)
    assert "📎 添加资料" in text
    assert "✅ 确认生成" in text
    assert "📝 调整目标" in text
    # 按钮 action 命名
    assert "pilot.ctx.add" in text
    assert "pilot.ctx.confirm" in text
    assert "pilot.ctx.adjust" in text


def test_context_summary_dataclass_translates_missing() -> None:
    s = ContextSummary(task_summary="x", missing=["audience", "form"])
    card = build_context_confirm_card(task_id="t", summary=s)
    text = _walk_text(card)
    assert "受众" in text
    assert "形态" in text
