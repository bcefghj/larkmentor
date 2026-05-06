"""ReviewAgent — 自评内容质量.

检查维度:
  - 是否有数据支撑
  - 是否结构完整（有标题/正文/结论）
  - 是否有引用来源

输出 JSON: {"pass": true/false, "feedback": "...", "issues": [...]}
写入 state["review_pass"] / state["review_feedback"]。
"""

from __future__ import annotations

import logging
from typing import Any

from pilot.agents.base import AgentState, BaseAgent

logger = logging.getLogger("pilot.agents.reviewer")

_REVIEWER_SYSTEM_PROMPT = """\
你是 Agent-Pilot 的质量审核员，负责检查文档草稿的内容质量。

审核维度：
1. 数据支撑：是否引用了具体数据、案例或权威来源
2. 结构完整：是否有标题、正文、结论；各章节是否连贯
3. 引用来源：是否标注了 [1] [2] 等脚注引用；来源是否真实可信
4. 内容密度：是否言之有物，避免空洞套话
5. 字数达标：每章节是否达到 300 字以上

输出严格 JSON：
{"pass": true或false, "feedback": "总体评价 50-100 字", "issues": ["问题1", "问题2"]}

pass=true 的标准：
- 至少 80% 的章节有数据引用
- 所有章节结构完整
- 总字数 >= 1500
- 无严重事实错误
"""


class ReviewAgent(BaseAgent):
    """审核 Agent：检查草稿质量，决定是否通过或需要修改。"""

    name = "review_agent"
    role = "质量审核员"
    system_prompt = _REVIEWER_SYSTEM_PROMPT

    async def execute(self, state: AgentState) -> AgentState:
        draft_sections = state.get("draft_sections", [])

        if not draft_sections:
            state["review_pass"] = False
            state["review_feedback"] = "无草稿内容可审核"
            return state

        full_draft = "\n\n".join(
            s.get("content", "") for s in draft_sections if isinstance(s, dict)
        )

        prompt = f"""请审核以下文档草稿的质量：

{full_draft[:6000]}

请按照审核维度（数据支撑、结构完整、引用来源、内容密度、字数达标）逐项检查，
输出 JSON：{{"pass": true/false, "feedback": "...", "issues": [...]}}
"""
        raw = await self._call_llm(prompt, temperature=0.2, max_tokens=1024)
        review = self._parse_review(raw)

        state["review_pass"] = review.get("pass", False)
        state["review_feedback"] = review.get("feedback", "")

        logger.info(
            "ReviewAgent: pass=%s feedback=%s issues=%d",
            review.get("pass"),
            review.get("feedback", "")[:60],
            len(review.get("issues", [])),
        )
        return state

    @staticmethod
    def _parse_review(raw: str) -> dict[str, Any]:
        from pilot.llm.safe_json import safe_json_parse

        obj = safe_json_parse(raw, expected_type=dict, debug_label="review.result")
        if obj and isinstance(obj, dict):
            return {
                "pass": bool(obj.get("pass", False)),
                "feedback": str(obj.get("feedback", "")),
                "issues": list(obj.get("issues", [])),
            }
        return {"pass": False, "feedback": raw[:200], "issues": ["无法解析审核结果"]}
