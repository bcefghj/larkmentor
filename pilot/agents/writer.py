"""WriterAgent — 逐章生成 Markdown 内容（支持并行）.

每章 300-500 字，要求引用研究数据。输出写入 state["draft_sections"]。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pilot.agents.base import AgentState, BaseAgent

logger = logging.getLogger("pilot.agents.writer")

_WRITER_SYSTEM_PROMPT = """\
你是 Agent-Pilot 的资深写作员，擅长结构化方案与汇报文档。
你可以联网搜索最新信息来丰富内容。

写作要求：
1. 每个章节 300-500 字，信息密度高
2. 必须引用研究数据，以 [1] [2] 脚注形式标注来源
3. 不要寒暄、不要"以下是为您生成的"之类元语言
4. 包含数据/案例/洞察，言之有物
5. 使用 Markdown 格式，包含二级标题 ##
6. 直接输出正文内容
"""


class WriterAgent(BaseAgent):
    """写作 Agent：逐章生成高质量 Markdown 内容。"""

    name = "writer_agent"
    role = "写作员"
    system_prompt = _WRITER_SYSTEM_PROMPT

    max_concurrent: int = 3

    async def execute(self, state: AgentState) -> AgentState:
        outline = state.get("outline", [])
        research = state.get("research_results", [])
        intent = state.get("intent", "")

        if not outline:
            state["draft_sections"] = []
            return state

        research_map: dict[str, dict[str, str]] = {}
        for r in research:
            if isinstance(r, dict):
                research_map[r.get("heading", "")] = {
                    "data": r.get("data", ""),
                    "source": r.get("source", ""),
                }

        sem = asyncio.Semaphore(self.max_concurrent)
        tasks = [
            self._write_section(section, research_map, intent, sem)
            for section in outline
            if isinstance(section, dict)
        ]
        sections = await asyncio.gather(*tasks, return_exceptions=True)

        draft_sections: list[dict[str, str]] = []
        for i, result in enumerate(sections):
            heading = outline[i].get("heading", f"章节 {i + 1}") if i < len(outline) else f"章节 {i + 1}"
            if isinstance(result, Exception):
                logger.warning("WriterAgent section %d failed: %s", i, result)
                draft_sections.append({
                    "heading": heading,
                    "content": f"## {heading}\n\n（内容生成失败，请重试）\n",
                })
            else:
                draft_sections.append(result)

        state["draft_sections"] = draft_sections

        total_chars = sum(len(s.get("content", "")) for s in draft_sections)
        logger.info("WriterAgent: %d sections, %d total chars", len(draft_sections), total_chars)
        return state

    async def _write_section(
        self,
        section: dict[str, Any],
        research_map: dict[str, dict[str, str]],
        intent: str,
        sem: asyncio.Semaphore,
    ) -> dict[str, str]:
        heading = section.get("heading", "")
        key_points = section.get("key_points", [])
        research_info = research_map.get(heading, {})

        research_block = ""
        if research_info.get("data"):
            research_block = (
                f"\n\n联网搜索到的真实数据（必须在正文中引用）：\n"
                f"数据：{research_info['data']}\n"
                f"来源：{research_info.get('source', '联网搜索')}\n"
            )

        prompt = f"""请为以下章节生成内容（300-500 字）：

文档主题：{intent}
章节标题：{heading}
要点：{', '.join(str(p) for p in key_points)}
{research_block}

要求：
1. 以 "## {heading}" 开头
2. 300-500 字，信息密度高
3. 必须引用上面搜索到的真实数据，在文中标注来源
4. 围绕文档主题「{intent}」展开，不要跑题
5. 包含具体数据、案例或洞察
6. 直接输出 Markdown 正文，不要元语言
"""
        async with sem:
            content = await self._call_llm(
                prompt,
                temperature=0.5,
                max_tokens=1024,
            )

        if not content or len(content) < 50:
            content = f"## {heading}\n\n{', '.join(str(p) for p in key_points)}\n"

        return {"heading": heading, "content": content}
