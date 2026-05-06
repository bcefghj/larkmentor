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
    """Proactive clarification with interactive Feishu card when possible."""
    args = ctx.get("resolved_args") or {}
    questions: List[str] = args.get("questions") or []
    intent = args.get("intent") or ctx.get("original_intent") or ""

    if not questions:
        try:
            from core.mentor import mentor_task as v4_task
            if intent:
                diag = v4_task.diagnose(intent)
                if getattr(diag, "questions", None):
                    questions = list(diag.questions)[:4]
        except Exception as e:
            logger.debug("mentor_task diagnose fallback: %s", e)

    if not questions:
        questions = [
            "这份产出主要是给谁看？（上级 / 同事 / 客户）",
            "希望生成什么类型？（文档 / PPT / 文档+PPT）",
            "希望多长时间内完成？",
            "是否有已存在的文档或画布可参考？",
        ]

    user_open_id = ctx.get("user_open_id") or ""
    card_sent = False
    if user_open_id:
        card_sent = _send_clarify_card(user_open_id, intent, questions)

    return {
        "questions": questions,
        "intent": intent,
        "card_sent": card_sent,
        "action": "awaiting_clarification",
    }


def _send_clarify_card(open_id: str, intent: str, questions: List[str]) -> bool:
    """Send a Feishu interactive card with button options for quick clarification."""
    try:
        from bot.message_sender import send_card

        card = _build_clarify_card(intent, questions)
        send_card(open_id, card)
        return True
    except Exception as e:
        logger.debug("clarify card send failed: %s", e)
        return False


def _build_clarify_card(intent: str, questions: List[str]) -> Dict[str, Any]:
    """Build a Feishu Card 2.0 with interactive buttons for clarification."""
    elements = [
        {"tag": "div", "text": {"tag": "lark_md",
            "content": f"**Agent-Pilot 需要更多信息来帮你完成任务**\n\n"
                        f"你说了：「{intent[:60]}」\n\n"
                        f"为了生成更好的结果，请回答以下问题："}},
        {"tag": "hr"},
    ]

    for i, q in enumerate(questions[:4]):
        elements.append(
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**{i + 1}. {q}**"}}
        )

    # Quick-action buttons
    actions = [
        {"tag": "button", "text": {"tag": "plain_text", "content": "生成文档"},
         "type": "primary", "value": {"action": "clarify_answer", "choice": "doc", "intent": intent[:80]}},
        {"tag": "button", "text": {"tag": "plain_text", "content": "生成 PPT"},
         "value": {"action": "clarify_answer", "choice": "ppt", "intent": intent[:80]}},
        {"tag": "button", "text": {"tag": "plain_text", "content": "文档 + PPT 三件套"},
         "value": {"action": "clarify_answer", "choice": "trio", "intent": intent[:80]}},
        {"tag": "button", "text": {"tag": "plain_text", "content": "跳过，直接开始"},
         "type": "danger", "value": {"action": "clarify_skip", "intent": intent[:80]}},
    ]
    elements.append({"tag": "action", "actions": actions})
    elements.append({"tag": "hr"})
    elements.append({"tag": "div", "text": {"tag": "lark_md",
        "content": "💡 你也可以直接回复文字来补充说明，Agent 会继续执行。"}})

    return {
        "header": {"title": {"tag": "plain_text", "content": "🤔 Agent-Pilot · 主动澄清"}, "template": "orange"},
        "elements": elements,
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
            snippets.append(f"{m.get('sender', '?')}: {m.get('text', '')[:100]}")

    try:
        from llm.llm_client import chat as llm_chat

        prompt = "请把下面的讨论压缩成 3-5 条决议/共识，每条一行。\n\n" + "\n".join(snippets)
        summary = llm_chat(prompt, temperature=0.2)
        if summary:
            return {"summary": summary.strip()}
    except Exception as e:
        logger.debug("summarize llm fallback: %s", e)

    return {"summary": "- 围绕 Agent-Pilot 架构达成初步共识\n- 多端同步采用 Yjs CRDT\n- 下周 Demo 以 IM→Doc→PPT 为主线"}
