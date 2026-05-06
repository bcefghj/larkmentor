"""PlannerAgent — 生成结构化大纲 JSON.

输出格式:
  {"title": "...", "sections": [{"heading": "...", "key_points": ["..."]}]}

写入 state["outline"]。
"""

from __future__ import annotations

import logging
from typing import Any

from pilot.agents.base import AgentState, BaseAgent

logger = logging.getLogger("pilot.agents.planner")

_PLANNER_SYSTEM_PROMPT = """\
你是 Agent-Pilot 的规划师，擅长将用户模糊的办公需求拆解为结构化大纲。
你可以联网搜索最新信息来辅助规划。

输出要求：
1. 严格输出 JSON（不要多余文字）
2. 格式：{"title": "文档标题", "sections": [{"heading": "章节标题", "key_points": ["要点1", "要点2"]}]}
3. sections 至少 5 个章节
4. 每个章节 2-4 个 key_points
5. 章节应包含：背景/现状、目标/受众、核心方案、数据/案例、风险/对策、结论/下一步
"""

_FALLBACK_OUTLINE: dict[str, Any] = {
    "title": "Agent-Pilot 方案文档",
    "sections": [
        {"heading": "背景与现状", "key_points": ["行业背景", "当前痛点", "关键变化"]},
        {"heading": "目标与受众", "key_points": ["核心目标", "受众画像", "时间节点"]},
        {"heading": "方案设计", "key_points": ["阶段一：现状盘点", "阶段二：核心动作", "阶段三：复盘调整"]},
        {"heading": "数据与案例", "key_points": ["行业数据", "典型案例", "内部基线"]},
        {"heading": "风险与对策", "key_points": ["资源风险", "进度风险", "质量风险"]},
        {"heading": "结论与下一步", "key_points": ["关键结论", "行动计划", "里程碑"]},
    ],
}


class PlannerAgent(BaseAgent):
    """大纲规划 Agent：将用户意图转换为结构化章节大纲。"""

    name = "planner_agent"
    role = "规划师"
    system_prompt = _PLANNER_SYSTEM_PROMPT

    async def execute(self, state: AgentState) -> AgentState:
        intent = state.get("intent", "")
        task_type = state.get("task_type", "doc")

        prompt = f"""请为以下任务生成结构化大纲：

用户意图：{intent}
产出类型：{task_type}

输出严格 JSON 格式：
{{"title": "...", "sections": [{{"heading": "...", "key_points": ["..."]}}]}}
"""
        raw = await self._call_llm(prompt, temperature=0.4, max_tokens=2048)
        outline = self._parse_outline(raw, intent)

        state["outline"] = outline.get("sections", [])
        state.setdefault("_title", outline.get("title", intent[:60]))  # type: ignore[typeddict-item]

        logger.info(
            "PlannerAgent: title=%s sections=%d",
            outline.get("title", "")[:40],
            len(outline.get("sections", [])),
        )
        return state

    @staticmethod
    def _parse_outline(raw: str, intent: str) -> dict[str, Any]:
        from pilot.llm.safe_json import safe_json_parse

        obj = safe_json_parse(raw, expected_type=dict, debug_label="planner.outline")
        if obj and isinstance(obj, dict) and obj.get("sections"):
            return obj

        fallback = dict(_FALLBACK_OUTLINE)
        fallback["title"] = intent[:60] or fallback["title"]
        return fallback
