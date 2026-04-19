"""Mentor skill registration · Claude Code 7 支柱 3 (Skills) 落地

Each of the 4 mentor capabilities (write / task / review / onboard) is
described as a ``SkillManifest`` and registered with ``default_loader``,
plus its underlying invocation function is registered with
``default_registry`` as a tool.

This is the single entry point that bot startup calls to wire up Skills:

    from core.mentor.skills_init import register_all
    register_all()

After this call:
- ``runtime.default_loader().list_skills()`` returns 4 skills
- ``runtime.default_loader().find_for_command("帮我看看 ...")`` matches mentor.write
- ``runtime.default_registry().invoke("mentor.write", {...})`` runs the skill

Why we don't import this at module load: it has side-effects (singleton
mutation), and we want tests to control when registration happens.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from core.runtime import (
    SkillManifest,
    ToolMetadata,
    default_loader,
    default_registry,
)

logger = logging.getLogger("flowguard.mentor.skills_init")


# ── Skill manifests ─────────────────────────────────────────


WRITE_SKILL = SkillManifest(
    name="mentor.write",
    version="2.0.0",
    description="消息草拟 · NVC 框架 + 3 版改写（保守/中性/直接）",
    tools=["mentor.write", "mentor.kb_search"],
    triggers=[
        "帮我看", "帮我写", "怎么回", "怎么写", "怎么说",
        "改一下", "润色", "代我回", "建议回复", "草拟",
    ],
    system_prompt=(
        "你是一位飞书 IM 的写作 Mentor。给定用户草稿和组织上下文，"
        "返回 NVC 4 段诊断 + 保守/中性/直接 3 版改写。永远不要替用户发送。"
    ),
    permission="DRAFT_ACTION",
)

TASK_SKILL = SkillManifest(
    name="mentor.task",
    version="2.0.0",
    description="任务澄清 · LLM 评模糊度 0-1，>0.5 给 2 个澄清问题",
    tools=["mentor.task"],
    triggers=[
        "任务", "需求", "deadline", "ddl", "交付", "拆解", "需求方",
        "任务确认", "确认任务",
    ],
    system_prompt=(
        "你是任务理解 Mentor。给定用户描述的任务，评估它是否清晰。"
        "若 ambiguity > 0.5，主动给出 2 个澄清问题让用户去和需求方确认。"
    ),
    permission="DRAFT_ACTION",
)

REVIEW_SKILL = SkillManifest(
    name="mentor.review",
    version="2.0.0",
    description="周报回顾 · STAR 结构 + 引用本周聊天/文档/任务自动追溯",
    tools=["mentor.review", "memory.query"],
    triggers=[
        "周报", "月报", "复盘", "weekly", "monthly", "wrapped",
        "写周报", "本周回顾",
    ],
    system_prompt=(
        "你是周报 Mentor。综合用户本周消息/文档/任务，生成 STAR 结构周报草稿，"
        "每条 bullet 引用至少一个来源。永远不要替用户发布。"
    ),
    permission="DRAFT_ACTION",
)

ONBOARD_SKILL = SkillManifest(
    name="mentor.onboard",
    version="2.0.0",
    description="新人入职 · 5 问知识沉淀流程",
    tools=["mentor.onboard.start", "mentor.onboard.answer"],
    triggers=[
        "重新入职", "开始入职", "入职引导", "新人引导", "onboarding",
    ],
    system_prompt=(
        "你是新人入职 Mentor。一次性问 5 个问题，把答案存入用户级 KB 作为最高优先级 context。"
    ),
    permission="DRAFT_ACTION",
    metadata={"questions_count": 5},
)


ALL_SKILLS = [WRITE_SKILL, TASK_SKILL, REVIEW_SKILL, ONBOARD_SKILL]


# ── Tool handlers (thin wrappers over existing mentor modules) ─


def _handle_write(user_open_id: str, content: str, recipient: str = "peer") -> Dict[str, Any]:
    from core.mentor.mentor_write import review
    wr = review(user_open_id, content, recipient=recipient)
    return wr.to_dict()


def _handle_task(user_open_id: str, content: str) -> Dict[str, Any]:
    try:
        from core.mentor.mentor_task import analyse
        result = analyse(user_open_id, content)
        return result.to_dict() if hasattr(result, "to_dict") else dict(result)
    except Exception as e:
        return {"error": str(e), "fallback": True}


def _handle_review(user_open_id: str, content: str = "") -> Dict[str, Any]:
    try:
        from core.mentor.mentor_review import draft_weekly_report
        result = draft_weekly_report(user_open_id, content or "")
        return result.to_dict() if hasattr(result, "to_dict") else dict(result)
    except Exception as e:
        return {"error": str(e), "fallback": True}


def _handle_onboard_start(user_open_id: str) -> Dict[str, Any]:
    try:
        from core.mentor.mentor_onboard import start_onboarding
        s = start_onboarding(user_open_id)
        return s.to_dict() if hasattr(s, "to_dict") else dict(s)
    except Exception as e:
        return {"error": str(e), "fallback": True}


def _handle_onboard_answer(user_open_id: str, answer: str) -> Dict[str, Any]:
    try:
        from core.mentor.mentor_onboard import submit_answer
        s = submit_answer(user_open_id, answer)
        return s.to_dict() if hasattr(s, "to_dict") else dict(s)
    except Exception as e:
        return {"error": str(e), "fallback": True}


# ── Registration ────────────────────────────────────────────


def register_all() -> Dict[str, int]:
    """Register all 4 mentor skills + tools. Idempotent."""

    loader = default_loader()
    registry = default_registry()

    # Re-register from a fresh copy each time so external mutations
    # (test fixtures disabling a skill etc.) don't leak across calls.
    for skill in ALL_SKILLS:
        loader.register(SkillManifest.from_dict(skill.to_dict()))

    registry.register(ToolMetadata(
        name="mentor.write",
        description=WRITE_SKILL.description,
        handler=_handle_write,
        permission="DRAFT_ACTION",
        skill="mentor.write",
        rate_limit_per_minute=20,
    ))
    registry.register(ToolMetadata(
        name="mentor.task",
        description=TASK_SKILL.description,
        handler=_handle_task,
        permission="DRAFT_ACTION",
        skill="mentor.task",
        rate_limit_per_minute=20,
    ))
    registry.register(ToolMetadata(
        name="mentor.review",
        description=REVIEW_SKILL.description,
        handler=_handle_review,
        permission="DRAFT_ACTION",
        skill="mentor.review",
        rate_limit_per_minute=10,
    ))
    registry.register(ToolMetadata(
        name="mentor.onboard.start",
        description="启动入职 5 问流",
        handler=_handle_onboard_start,
        permission="DRAFT_ACTION",
        skill="mentor.onboard",
        rate_limit_per_minute=5,
    ))
    registry.register(ToolMetadata(
        name="mentor.onboard.answer",
        description="提交一个入职答案",
        handler=_handle_onboard_answer,
        permission="DRAFT_ACTION",
        skill="mentor.onboard",
        rate_limit_per_minute=20,
    ))

    stats = {
        "skills_registered": len(loader.list_skills()),
        "tools_registered": len(registry.list_tools()),
    }
    logger.info("mentor skills registered: %s", stats)
    return stats
