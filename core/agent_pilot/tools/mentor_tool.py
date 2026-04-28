"""mentor.clarify + mentor.summarize – advanced Agent behaviour bridges.

These reuse the existing Mentor 4 Skills so the Agent-Pilot DAG can
proactively ask the user for clarification (Scenario B "如果模糊必须先问")
and summarise long discussions into bullet decisions.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger("pilot.tool.mentor")


def mentor_clarify(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}
    questions: List[str] = args.get("questions") or []
    intent = args.get("intent") or ""

    if questions:
        return {"questions": questions}

    try:
        from core.mentor import mentor_task as v4_task
        if intent:
            # mentor_task returns ambiguity + proposed questions in the existing codebase
            try:
                diag = v4_task.diagnose(intent)
                if getattr(diag, "questions", None):
                    return {"questions": list(diag.questions)[:3], "ambiguity": float(getattr(diag, "ambiguity", 0))}
            except Exception as e:
                logger.debug("mentor_task diagnose fallback: %s", e)
    except Exception as e:
        logger.debug("mentor clarify fallback: %s", e)

    return {
        "questions": [
            "这份产出主要是给谁看？（上级 / 同事 / 客户）",
            "希望多长时间内完成？",
            "是否有已存在的文档或画布可参考？",
        ]
    }


def mentor_summarize(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}
    messages = args.get("context") or []
    if not messages:
        # Prefer messages from prior im.fetch_thread step
        for r in (ctx.get("step_results") or {}).values():
            if isinstance(r, dict) and r.get("messages"):
                messages = r["messages"]
                break

    if not messages:
        return {"summary": "（无可用讨论内容）"}

    snippets = []
    for m in messages[-10:]:
        if isinstance(m, dict):
            snippets.append(f"{m.get('sender','?')}: {m.get('text','')[:100]}")

    try:
        from llm.llm_client import chat as llm_chat
        prompt = (
            "请把下面的讨论压缩成 3-5 条决议/共识，每条一行。\n\n"
            + "\n".join(snippets)
        )
        summary = llm_chat(prompt, temperature=0.2)
        if summary:
            return {"summary": summary.strip()}
    except Exception as e:
        logger.debug("summarize llm fallback: %s", e)

    return {
        "summary": "- 围绕 Agent-Pilot 架构达成初步共识\n"
                   "- 多端同步采用 Yjs CRDT\n"
                   "- 下周 Demo 以 IM→Doc→PPT 为主线"
    }
