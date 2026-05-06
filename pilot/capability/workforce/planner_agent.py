"""Planner Agent — 把 1-4 句 prompt 扩成完整产品 spec.

Anthropic 教训：spec 不要写实现细节，否则下游 generator 会被锁死。
专注于：
  - 受众
  - 输出形态
  - 功能清单
  - 风险
  - 不写"怎么做"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pilot.llm.client import default_client
from pilot.llm.safe_json import safe_json_parse

logger = logging.getLogger("pilot.workforce.planner")


@dataclass
class ProductSpec:
    title: str = ""
    audience: str = ""  # leader / colleague / customer / self
    primary_outputs: list[str] = field(default_factory=list)  # ["doc", "slide", "canvas"]
    feature_list: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    sprints: list[dict[str, Any]] = field(default_factory=list)
    raw_intent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "audience": self.audience,
            "primary_outputs": self.primary_outputs,
            "feature_list": self.feature_list,
            "constraints": self.constraints,
            "risks": self.risks,
            "sprints": self.sprints,
            "raw_intent": self.raw_intent,
        }


_PLANNER_SYSTEM = """你是 Agent-Pilot 工坊的产品规划师（Planner）。
你接到一句简短的用户意图，需要扩写成一份完整的产品 spec。

## 三条铁律
1. 不写"怎么做"——只写要交付什么、给谁、有什么约束
2. 把整个任务拆成 1-5 个 sprint，每个 sprint 是一个独立可交付的子任务
3. 输出严格 JSON，不要 markdown 代码块、不要解释"""


_PLANNER_USER_TEMPLATE = """用户意图: {intent}

请输出严格 JSON:
{{
  "title": "...",
  "audience": "leader|colleague|customer|self",
  "primary_outputs": ["doc"|"slide"|"canvas"],
  "feature_list": ["...", "..."],
  "constraints": ["..."],
  "risks": ["..."],
  "sprints": [
    {{"sprint_index": 1, "title": "...", "goal": "..."}},
    {{"sprint_index": 2, "title": "...", "goal": "..."}}
  ]
}}

要求：feature_list 至少 3 项；sprints 至少 1 项；不要解释。"""


class PlannerAgent:
    async def plan(self, *, intent: str) -> ProductSpec:
        intent = (intent or "").strip()
        try:
            client = default_client()
            result = await client.chat(
                system=_PLANNER_SYSTEM,
                messages=[{"role": "user", "content": _PLANNER_USER_TEMPLATE.format(intent=intent)}],
                temperature=0.3,
                max_tokens=2048,
            )
            text = ""
            for block in result.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    break
            obj = safe_json_parse(text, expected_type=dict, debug_label="planner")
            if obj:
                return ProductSpec(
                    title=obj.get("title", intent[:40]),
                    audience=obj.get("audience", ""),
                    primary_outputs=obj.get("primary_outputs", ["doc"]),
                    feature_list=obj.get("feature_list", []),
                    constraints=obj.get("constraints", []),
                    risks=obj.get("risks", []),
                    sprints=obj.get("sprints", []),
                    raw_intent=intent,
                )
        except Exception as e:
            logger.warning("planner LLM failed: %s", e)

        # 启发式回退
        return self._heuristic(intent)

    @staticmethod
    def _heuristic(intent: str) -> ProductSpec:
        outputs = []
        if any(k in intent for k in ("文档", "方案", "报告", "复盘", "需求")):
            outputs.append("doc")
        if any(k in intent for k in ("画布", "白板", "架构图", "流程图")):
            outputs.append("canvas")
        if any(k in intent for k in ("PPT", "ppt", "演示", "汇报", "幻灯")):
            outputs.append("slide")
        if not outputs:
            outputs = ["doc"]

        sprints = []
        for i, out in enumerate(outputs, start=1):
            sprints.append({
                "sprint_index": i,
                "title": {"doc": "生成方案文档", "canvas": "绘制架构图", "slide": "生成演示稿"}.get(out, "执行"),
                "goal": f"产出 {out} 形态的初稿",
            })
        sprints.append({
            "sprint_index": len(sprints) + 1,
            "title": "归档分享",
            "goal": "汇总产物 + 生成分享链接",
        })

        return ProductSpec(
            title=intent[:40] or "Agent-Pilot 任务",
            audience="leader",
            primary_outputs=outputs,
            feature_list=["满足用户意图描述的核心需求", "包含数据/案例", "结构化交付"],
            constraints=["无截止时间提示"],
            risks=["LLM 生成内容可能不准确"],
            sprints=sprints,
            raw_intent=intent,
        )
