"""mentor.clarify / mentor.summarize — Advanced Agent 能力（Good-2 加分项）."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("pilot.tool.mentor")


def register_to(reg) -> None:
    reg.register(
        "mentor.clarify",
        description="主动向用户提问以澄清模糊意图",
        input_schema={
            "type": "object",
            "properties": {
                "questions": {"type": "array", "items": {"type": "string"}},
                "intent": {"type": "string"},
            },
        },
        read_only=False,
        namespace="pilot",
    )(mentor_clarify)

    reg.register(
        "mentor.summarize",
        description="对一段讨论做结构化总结，输出 3-5 条决议",
        input_schema={
            "type": "object",
            "properties": {
                "context": {"type": "array", "description": "discussion messages"},
            },
        },
        read_only=True,
        namespace="pilot",
    )(mentor_summarize)


async def mentor_clarify(
    *,
    questions: list | None = None,
    intent: str = "",
    _ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    qs = list(questions or []) or [
        "这份产出主要是给谁看？（上级 / 同事 / 客户）",
        "希望生成什么类型？（文档 / PPT / 文档+PPT）",
        "希望多长时间内完成？",
        "是否有已存在的文档或画布可参考？",
    ]
    return {
        "action": "awaiting_clarification",
        "questions": qs,
        "intent": intent,
        "card_kind": "clarify",
    }


async def mentor_summarize(
    *,
    context: list | None = None,
    _ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    msgs = context or []
    if not msgs and _ctx:
        # 从 step_results 找 im.fetch_thread
        for r in (_ctx.get("step_results") or {}).values():
            if isinstance(r, dict) and r.get("messages"):
                msgs = r["messages"]
                break

    if not msgs:
        return {"summary": "（无可用讨论内容）"}

    # 简单提炼（生产中接 LLM）
    snippets = []
    for m in msgs[-10:]:
        if isinstance(m, dict):
            snippets.append(f"- {m.get('sender', '?')}: {m.get('text', '')[:60]}")

    summary = "## 讨论要点\n\n" + "\n".join(snippets[:6])
    try:
        from pilot.llm.client import default_client

        prompt = f"请把以下讨论压缩成 3-5 条决议/共识，每条一行（不要寒暄）：\n\n" + "\n".join(snippets)
        client = default_client()
        result = await client.chat(
            system="你是 Agent-Pilot 的总结员，擅长把会议讨论转成可执行的决议。",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=600,
        )
        for block in result.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text", "").strip()
                if t:
                    summary = t
                    break
    except Exception as e:
        logger.debug("summarize llm failed, fall back: %s", e)

    return {"summary": summary}
