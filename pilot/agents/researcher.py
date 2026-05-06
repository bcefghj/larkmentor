"""ResearchAgent — 为每个章节联网搜索数据.

利用 MiniMax 的 tool calling（web_search function）为大纲中每个章节
搜索相关数据与案例，汇总到 state["research_results"]。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pilot.agents.base import AgentState, BaseAgent

logger = logging.getLogger("pilot.agents.researcher")

_RESEARCH_SYSTEM_PROMPT = """\
你是 Agent-Pilot 的研究员，擅长联网搜索最新信息来支撑文档内容。
你拥有 web_search 工具，请为每个章节搜索 1-2 个关键词，获取真实数据、案例和来源。

搜索策略：
1. 根据章节标题和要点提炼搜索关键词（中文或英文均可）
2. 优先搜索：行业数据、权威报告、最新政策、典型案例
3. 每次搜索后整理要点，标注来源 URL

回复格式（纯 JSON 数组）：
[
  {
    "heading": "章节标题",
    "search_query": "搜索关键词",
    "findings": [
      {"title": "来源标题", "url": "来源URL", "snippet": "关键摘要 50-100 字"}
    ]
  }
]
"""

WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "联网搜索最新信息",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                },
            },
            "required": ["query"],
        },
    },
}


class ResearchAgent(BaseAgent):
    """研究员 Agent：为大纲章节联网搜索数据。"""

    name = "research_agent"
    role = "研究员"
    system_prompt = _RESEARCH_SYSTEM_PROMPT

    async def execute(self, state: AgentState) -> AgentState:
        outline = state.get("outline", [])
        intent = state.get("intent", "")

        if not outline:
            state["research_results"] = []
            return state

        sections_desc = "\n".join(
            f"- {s.get('heading', '')}: {', '.join(s.get('key_points', []))}"
            for s in outline
            if isinstance(s, dict)
        )

        prompt = f"""请为以下文档大纲的每个章节搜索相关数据。

用户意图：{intent}

大纲章节：
{sections_desc}

请使用 web_search 工具搜索每个章节的关键信息，然后汇总输出 JSON 数组。
每个章节搜索 1-2 个关键词，重点搜索数据、案例、来源。
"""
        result = await self._call_llm_raw(
            prompt,
            tools=[WEB_SEARCH_TOOL],
            temperature=0.3,
            max_tokens=4096,
        )

        research = self._extract_research(result, outline)
        state["research_results"] = research

        logger.info(
            "ResearchAgent: %d sections researched, %d total findings",
            len(research),
            sum(len(r.get("findings", [])) for r in research),
        )
        return state

    def _extract_research(
        self, result: dict[str, Any], outline: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """从 LLM 回复中提取研究结果。

        处理两种情况：
        1. LLM 直接返回 JSON 结果
        2. LLM 先调 web_search tool_call，再返回结果
        """
        from pilot.llm.safe_json import safe_json_parse

        text = result.get("text", "")
        if text:
            parsed = safe_json_parse(text, expected_type=list, debug_label="research.results")
            if parsed:
                return parsed

        tool_calls = result.get("tool_calls", [])
        findings: list[dict[str, Any]] = []

        for section in outline:
            if not isinstance(section, dict):
                continue
            heading = section.get("heading", "")
            section_findings: list[dict[str, str]] = []

            for tc in tool_calls:
                fn = tc.get("function", {}) or {}
                if fn.get("name") == "web_search":
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except Exception:
                        args = {}
                    section_findings.append({
                        "title": f"搜索: {args.get('query', '')}",
                        "url": "",
                        "snippet": f"(web_search tool_call for: {args.get('query', '')})",
                    })

            findings.append({
                "heading": heading,
                "search_query": heading,
                "findings": section_findings or [
                    {"title": f"{heading} 相关资料", "url": "", "snippet": "待联网搜索补充"}
                ],
            })

        return findings
