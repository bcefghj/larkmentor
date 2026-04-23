"""Mentor Tools · 把原 core/mentor/ 10 个模块塌缩为 @tool。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .registry import tool

logger = logging.getLogger("agent.tools.mentor")


@tool(
    name="mentor.reply_draft",
    description="根据上下文起草 3 个候选回复（NVC 框架），永不自动发送",
    permission="readonly",
    team="mentor",
)
def reply_draft(
    content: str = "",
    context: str = "",
    user_open_id: str = "",
) -> Dict[str, Any]:
    try:
        from core.mentor import mentor_write
        result = mentor_write.review(content, context=context)
        return {"ok": True, **(result or {})}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="mentor.clarify",
    description="主动任务澄清 - 检测模糊点并生成澄清问题",
    permission="readonly",
    team="mentor",
)
def clarify_task(task_text: str = "", user_open_id: str = "") -> Dict[str, Any]:
    try:
        from core.mentor import mentor_task
        result = mentor_task.clarify(task_text)
        return {"ok": True, **(result or {})}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="mentor.weekly_report",
    description="生成 STAR 结构周报（Situation/Task/Action/Result），带引用",
    permission="readonly",
    team="mentor",
)
def weekly_report(user_open_id: str = "", week_offset: int = 0) -> Dict[str, Any]:
    try:
        from core.mentor import mentor_review
        result = mentor_review.draft(user_open_id=user_open_id, week_offset=week_offset)
        return {"ok": True, **(result or {})}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="mentor.onboard_next",
    description="新人入职 5 问的下一步",
    permission="readonly",
    team="mentor",
)
def onboard_next(user_open_id: str = "", answer: str = "") -> Dict[str, Any]:
    try:
        from core.mentor import mentor_onboard
        if answer:
            result = mentor_onboard.submit_answer(user_open_id, answer)
        else:
            session = mentor_onboard.get_session(user_open_id)
            result = {"session": session.__dict__ if session else None}
        return {"ok": True, **(result or {})}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="mentor.recommend_next",
    description="高级 Agent：根据上下文推荐下一步行动（LARKMENTOR.md 规则 + 最近 transcript）",
    permission="readonly",
    team="any",
)
def recommend_next(recent_context: str = "", user_open_id: str = "") -> Dict[str, Any]:
    try:
        from core.agent_pilot.advanced_agent import recommend_next_steps
        result = recommend_next_steps(recent_context)
        return {"ok": True, "recommendations": result}
    except Exception as e:
        logger.debug("recommend_next fallback: %s", e)
        from ..providers import default_providers
        text = default_providers().chat(
            messages=[{"role": "user", "content": f"根据以下对话，推荐 3 个下一步：\n\n{recent_context[:2000]}"}],
            task_kind="summary", max_tokens=600,
        )
        return {"ok": True, "recommendations": text}
