"""Module 5: Rookie Buddy – workplace communication coaching with org-style awareness."""

import logging

from llm.llm_client import chat_json, chat
from llm.prompts import ROOKIE_REVIEW_PROMPT, ROOKIE_TASK_CONFIRM_PROMPT, ROOKIE_WEEKLY_PROMPT
from memory.user_state import get_org_docs_context

logger = logging.getLogger("flowguard.rookie")


def _org_ctx() -> str:
    docs = get_org_docs_context()
    if docs:
        return f"\n== 组织参考文档/风格 ==\n{docs}\n\n请参考以上组织风格给出建议。\n"
    return ""


def review_message(message: str, recipient: str = "同事/上级") -> dict:
    prompt = ROOKIE_REVIEW_PROMPT.format(
        message=message, recipient=recipient, org_context=_org_ctx(),
    )
    result = chat_json(prompt)
    if not result:
        return {
            "risk_level": "low", "risk_description": "",
            "improved_version": message, "explanation": "无法分析，建议自行检查。",
        }
    return result


def generate_task_confirmation(task_description: str, assigner: str = "上级") -> str:
    prompt = ROOKIE_TASK_CONFIRM_PROMPT.format(
        task_description=task_description, assigner=assigner, org_context=_org_ctx(),
    )
    result = chat(prompt, temperature=0.4)
    if not result:
        return f"收到任务，我理解的要点如下：\n- {task_description[:100]}\n\n如有偏差请指正。"
    return result


def generate_weekly_report(work_content: str) -> str:
    prompt = ROOKIE_WEEKLY_PROMPT.format(
        work_content=work_content, org_context=_org_ctx(),
    )
    result = chat(prompt, temperature=0.5)
    if not result:
        return f"本周工作内容：\n{work_content}\n\n（周报生成失败，请手动补充。）"
    return result
