"""Clarifier — 主动澄清（PRD §G2 加分项）.

集成到飞书澄清卡片：
  - 4 个一键按钮（生成文档 / 生成 PPT / 三件套 / 跳过）
  - 用户点完按钮自动重启 plan
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("pilot.workforce.clarifier")


@dataclass
class ClarifyRequest:
    intent: str
    questions: list[str] = field(default_factory=list)
    quick_choices: list[dict[str, str]] = field(default_factory=lambda: [
        {"action": "pilot.clarify.choose", "choice": "doc", "label": "生成文档"},
        {"action": "pilot.clarify.choose", "choice": "ppt", "label": "生成 PPT"},
        {"action": "pilot.clarify.choose", "choice": "trio", "label": "文档 + PPT 三件套"},
        {"action": "pilot.clarify.skip", "choice": "skip", "label": "跳过，直接开始"},
    ])

    def to_card(self) -> dict[str, Any]:
        """生成飞书 Card 2.0 schema（基础版；CardKit 2.0 增强版在 surface 层）."""
        elements = [
            {"tag": "div", "text": {"tag": "lark_md",
                                    "content": f"**Agent-Pilot 需要更多信息来帮你完成任务**\n\n你说了：「{self.intent[:60]}」\n\n为了生成更好的结果，请回答以下问题："}},
            {"tag": "hr"},
        ]
        for i, q in enumerate(self.questions[:4]):
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**{i + 1}. {q}**"}})

        actions = [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": choice["label"]},
                "type": "primary" if choice["choice"] == "doc" else ("danger" if choice["choice"] == "skip" else "default"),
                "value": {"action": choice["action"], "choice": choice["choice"], "intent": self.intent[:80]},
            }
            for choice in self.quick_choices
        ]
        elements.append({"tag": "action", "actions": actions})
        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md",
                                                "content": "💡 你也可以直接回复文字来补充说明，Agent 会继续执行。"}})

        return {
            "header": {"title": {"tag": "plain_text", "content": "🤔 Agent-Pilot · 主动澄清"}, "template": "orange"},
            "elements": elements,
        }


class Clarifier:
    """主动澄清 facade."""

    DEFAULT_QUESTIONS = [
        "希望什么时候完成或交付？",
        "面向的汇报对象是谁？（上级 / 同事 / 客户）",
        "请问希望覆盖的具体范围？",
    ]

    def build_request(self, *, intent: str, questions: list[str] | None = None) -> ClarifyRequest:
        return ClarifyRequest(
            intent=intent,
            questions=list(questions or self.DEFAULT_QUESTIONS),
        )

    def expand_choice(self, *, intent: str, choice: str) -> str:
        """把按钮 choice 转回完整意图."""
        intent = intent or ""
        if choice == "doc":
            if "文档" not in intent and "方案" not in intent:
                return f"{intent}（请生成方案文档）"
            return intent
        if choice == "ppt":
            if "PPT" not in intent and "演示" not in intent:
                return f"{intent}（请生成 PPT）"
            return intent
        if choice == "trio":
            if "三件套" not in intent:
                return f"{intent}（请生成文档 + 架构图 + PPT 三件套）"
            return intent
        # skip
        return intent
