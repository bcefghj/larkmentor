"""ResearchAgent — 利用 MiniMax 原生联网能力为大纲章节搜索数据.

MiniMax M2.7 Token Plan 自带联网搜索能力，模型在生成回复时会自动
查询互联网获取实时信息。无需任何第三方搜索引擎（DDG/Bing等）。
"""

from __future__ import annotations

import logging
from typing import Any

from pilot.agents.base import AgentState, BaseAgent

logger = logging.getLogger("pilot.agents.researcher")

_RESEARCH_SYSTEM_PROMPT = """\
你是 Agent-Pilot 的研究员。你拥有联网搜索能力，请充分利用。
任务：为用户文档的每个章节搜索最新的真实数据。

时间要求（重要！）：
- 当前时间是 2026 年 5 月，只接受 2024-2026 年的数据
- 拒绝使用 2023 年及更早的过时信息
- 如果搜到的数据没有明确年份，请注明"截至2026年"

质量标准：
1. 每个章节必须包含至少 1 个具体数字（市场规模、增长率、用户数等）
2. 必须标注权威来源（Gartner/IDC/麦肯锡/艾瑞等）
3. 优先引用一手数据源而非二手转述
4. 搜索不到就明确写"未找到该领域2024年后的公开数据"

好的搜索结果示例：
{"heading": "市场规模", "data": "据IDC 2025年报告，全球AI Agent市场规模达420亿美元，同比增长67%。中国市场占比约18%，预计2026年突破100亿美元。", "source": "IDC Worldwide AI Agent Market Forecast 2025-2028"}

差的搜索结果示例（请避免）：
{"heading": "市场规模", "data": "AI Agent市场正在快速增长，前景广阔", "source": "网络资料"}

输出格式（纯 JSON 数组，不要其他内容）：
[
  {"heading": "章节标题", "data": "搜索到的关键数据（100-200字，含具体数字和事实）", "source": "数据来源（机构/报告名/年份）"}
]
"""


class ResearchAgent(BaseAgent):
    """研究员 Agent：利用 MiniMax 原生联网搜索为大纲章节获取真实数据。"""

    name = "research_agent"
    role = "研究员"
    system_prompt = _RESEARCH_SYSTEM_PROMPT

    async def execute(self, state: AgentState) -> AgentState:
        """调用 MiniMax 联网搜索，为每个章节获取真实数据。

        MiniMax Token Plan 模型自带联网搜索能力：
        - 在 system prompt 中要求联网搜索
        - 模型会自动搜索互联网并返回带来源的数据
        - 无需 DDG/Bing 等第三方搜索引擎
        """
        outline = state.get("outline", [])
        intent = state.get("intent", "")

        if not outline:
            state["research_results"] = []
            return state

        sections_desc = "\n".join(
            f"- {s.get('heading', '')}: {', '.join(s.get('key_points', []))}"
            for s in outline if isinstance(s, dict)
        )

        prompt = f"""请联网搜索以下文档大纲每个章节所需的真实数据。

用户意图：{intent}

大纲章节：
{sections_desc}

请对每个章节进行联网搜索，获取：
- 最新行业数据（市场规模、增长率、用户数等具体数字）
- 权威报告或研究（Gartner、IDC、麦肯锡等）
- 具体企业案例或产品数据
- 信息来源标注

输出 JSON 数组：
[
  {{"heading": "章节标题", "data": "搜索到的关键数据和事实（100-200字，含具体数字）", "source": "数据来源"}}
]"""

        result = await self._call_llm(prompt, temperature=0.3, max_tokens=4096)

        research = self._parse_research(result, outline)
        state["research_results"] = research

        logger.info("ResearchAgent: %d sections researched via MiniMax", len(research))
        return state

    def _parse_research(self, text: str, outline: list) -> list[dict[str, Any]]:
        """解析 MiniMax 返回的研究结果 JSON。"""
        from pilot.llm.safe_json import safe_json_parse

        parsed = safe_json_parse(text, expected_type=list, debug_label="research")
        if parsed:
            return parsed

        research = []
        for section in outline:
            if not isinstance(section, dict):
                continue
            heading = section.get("heading", "")
            research.append({
                "heading": heading,
                "data": text[:200] if text else f"{heading} 相关数据",
                "source": "MiniMax 联网搜索",
            })
        return research
