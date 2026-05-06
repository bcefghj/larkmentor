"""IntentAgent — 用 MiniMax 判断用户意图，替代 5 闸门 IntentRouter.

输出三分类:
  - task:    明确的办公任务（写文档/做PPT/画架构图/三件套等）
  - chat:    闲聊/打招呼/感谢/问候
  - clarify: 可能是任务但信息不足，需追问

返回结构化 JSON 写入 state["intent"] / state["task_type"]。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pilot.agents.base import AgentState, BaseAgent

logger = logging.getLogger("pilot.agents.intent")

_INTENT_SYSTEM_PROMPT = """\
你是飞书办公助手 Agent-Pilot 的意图分类器。
判断用户消息属于以下哪类：
- task: 明确的办公任务（写文档/做PPT/画架构图/三件套等）
- chat: 闲聊/打招呼/感谢/问候
- clarify: 可能是任务但信息不足

task_type 说明：
- doc: 写文档/报告/方案
- ppt: 做PPT/演示稿
- trio: 三件套（文档+PPT+附件包）
- canvas: 画图/架构图/流程图
- none: 非任务时填 none

只输出 JSON: {"verdict":"task|chat|clarify","task_type":"doc|ppt|trio|canvas|none","summary":"一句话概括用户意图"}
"""


class IntentAgent(BaseAgent):
    """意图分类 Agent：判断 task / chat / clarify。"""

    name = "intent_agent"
    role = "意图分类器"
    system_prompt = _INTENT_SYSTEM_PROMPT

    async def execute(self, state: AgentState) -> AgentState:
        user_text = state.get("intent", "")
        if not user_text:
            state["task_type"] = "none"
            return state

        raw = await self._call_llm(
            user_text,
            temperature=0.1,
            max_tokens=256,
        )

        parsed = self._parse_verdict(raw)
        state["intent"] = user_text
        state["task_type"] = parsed.get("task_type", "doc")
        state.setdefault("_verdict", parsed.get("verdict", "task"))  # type: ignore[typeddict-item]
        state.setdefault("_summary", parsed.get("summary", user_text[:100]))  # type: ignore[typeddict-item]

        logger.info(
            "IntentAgent: verdict=%s task_type=%s summary=%s",
            parsed.get("verdict"),
            parsed.get("task_type"),
            parsed.get("summary", "")[:60],
        )
        return state

    @staticmethod
    def _parse_verdict(raw: str) -> dict[str, Any]:
        """从 LLM 回复中提取 JSON verdict。"""
        from pilot.llm.safe_json import safe_json_parse

        obj = safe_json_parse(raw, expected_type=dict, debug_label="intent.verdict")
        if obj and isinstance(obj, dict):
            return {
                "verdict": obj.get("verdict", "task"),
                "task_type": obj.get("task_type", "doc"),
                "summary": obj.get("summary", ""),
            }
        # fallback：原文无法解析时默认 task
        return {"verdict": "task", "task_type": "doc", "summary": raw[:100]}
