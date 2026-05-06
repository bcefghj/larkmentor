"""上下文确认卡片便利构造器（PRD §7.2）.

V1.5 设计要点：
  - 显式区分"已理解任务摘要" / "已用资料" / "缺失资料" 三段
  - 3 个动作按钮：📎 添加资料 / ✅ 确认生成 / 📝 调整目标
  - 与 builder.py 中 context_confirm_card() 行为完全一致；本模块提供更强类型 + 中转便利

用法：
    from pilot.surface.feishu.cards.context_confirm_card import build, ContextSummary
    card = build(task_id="task_xxx", summary=ContextSummary(
        task_summary="为 Q4 OKR 撰写汇报材料",
        used=["飞书文档：Q3 OKR 复盘", "群聊纪要 2026-04-30"],
        missing=["audience", "time"],
    ))
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from pilot.surface.feishu.cards.builder import context_confirm_card

MISSING_LABELS = {
    "audience": "受众（给谁看）",
    "form": "形态（文档 / PPT / 三件套）",
    "goal": "核心目标",
    "time": "截止时间",
}


@dataclass
class ContextSummary:
    task_summary: str = ""
    task_goal: str = ""
    used: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def to_card_kwargs(self) -> dict[str, Any]:
        return {
            "task_summary": self.task_summary,
            "task_goal": self.task_goal,
            "used": list(self.used),
            "missing": [MISSING_LABELS.get(m, m) for m in self.missing],
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build(*, task_id: str, summary: ContextSummary | dict[str, Any]) -> dict[str, Any]:
    if isinstance(summary, ContextSummary):
        return context_confirm_card(task_id=task_id, summary=summary.to_card_kwargs())
    if isinstance(summary, dict):
        return context_confirm_card(task_id=task_id, summary=summary)
    raise TypeError(f"summary 必须是 ContextSummary 或 dict，收到 {type(summary).__name__}")
