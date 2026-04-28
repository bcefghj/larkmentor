"""Advanced Agent capabilities (P4.2).

Three public entry points correspond to the three Good-to-have bullets:

* ``proactive_clarify(intent, context)`` — measures ambiguity, returns a
  clarify card payload or ``None``. The planner consults this before kicking
  off an irreversible plan.
* ``summarize_discussion(messages)`` — condenses an IM thread into
  Decision / Action-Item / Open-Questions using the harness LLM.
* ``recommend_next_steps(plan, user)`` — suggests follow-up actions based
  on LARKMENTOR.md rules + recent transcripts stored in Mem0g.

All three degrade gracefully when the LLM / Mem0g are unavailable — they
return empty results rather than raising.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("pilot.advanced")


@dataclass
class ClarifyRequest:
    ambiguity: float
    missing_dims: List[str]
    suggested_question: str
    options: List[str]


_DIM_HINTS = [
    ("对象", r"给(?:谁|哪|何)|对象|受众|客户|评委"),
    ("时间", r"(今晚|明天|下周|上午|月底|\d+日|\d+月|deadline|截止)"),
    ("形式", r"(文档|PPT|slide|白板|canvas|演讲|简报)"),
    ("篇幅", r"(\d+(?:页|字|分钟|s|秒))"),
    ("重点", r"(重点|突出|强调|核心)"),
]


def proactive_clarify(intent: str,
                      *,
                      chat_context: Optional[Iterable[Dict[str, Any]]] = None,
                      min_chars: int = 10) -> Optional[ClarifyRequest]:
    """Return a ClarifyRequest when the intent is ambiguous enough."""
    intent = (intent or "").strip()
    if len(intent) < min_chars:
        return ClarifyRequest(
            ambiguity=0.9,
            missing_dims=["具体需求"],
            suggested_question="想让我为你做什么？请多说两句，比如对象、形式、时间",
            options=["评审 PPT", "产品方案文档", "架构图", "周报草稿"],
        )

    missing: List[str] = []
    for label, pat in _DIM_HINTS:
        if not re.search(pat, intent):
            missing.append(label)

    # Heuristic ambiguity score: fraction of dims missing, capped to 0.9.
    amb = min(0.9, len(missing) / max(1, len(_DIM_HINTS)))
    if amb < 0.5:
        return None

    q = _render_question(intent, missing)
    opts = _render_options(missing)
    return ClarifyRequest(
        ambiguity=round(amb, 2),
        missing_dims=missing,
        suggested_question=q,
        options=opts,
    )


def _render_question(intent: str, missing: List[str]) -> str:
    base = f"收到「{intent[:40]}…」。为了做准，我想确认一下"
    hints = "、".join(missing[:2]) or "关键要素"
    return f"{base}**{hints}**，可以吗？"


def _render_options(missing: List[str]) -> List[str]:
    opts: List[str] = []
    if "对象" in missing:
        opts += ["给评委看", "给客户看", "团队内部"]
    if "形式" in missing:
        opts += ["PPT", "飞书文档", "画布"]
    if "时间" in missing:
        opts += ["今晚", "本周内"]
    # dedupe preserving order
    seen = set()
    final: List[str] = []
    for o in opts:
        if o not in seen:
            seen.add(o); final.append(o)
    return final[:4] or ["继续执行", "让我重新描述"]


# ── Summarise discussion ──────────────────────────────────────────────────────


_SUMMARY_PROMPT = """你是 LarkMentor 的总结助手。读完下列 IM 讨论后，用中文输出 3 段：

1. **决议（Decision）**：落地结论或已形成的共识，没有则写「无」
2. **行动项（Action Items）**：责任人@名 → 动作 → 截止时间（逐行 `- `）
3. **开放问题（Open Questions）**：还没回答 / 需要下一次会议确认的

要求：
- 每段 ≤ 5 行，不要总结过程、不要逐字复述；
- 没有的段落直接写「无」；
- 使用飞书文档兼容的 lark_md 语法。

讨论：
{thread}
"""


def summarize_discussion(messages: List[Dict[str, Any]],
                         *, max_chars: int = 4000) -> Dict[str, str]:
    """Take IM messages (dicts with ``sender``/``content``) and return a
    structured decision / actions / questions dict."""
    if not messages:
        return {"decisions": "无", "actions": "无", "questions": "无", "raw": ""}
    lines = []
    total = 0
    for m in messages:
        sender = m.get("sender") or m.get("sender_name") or "?"
        content = (m.get("content") or m.get("text") or "").strip()
        if not content:
            continue
        line = f"{sender}: {content}"
        if total + len(line) > max_chars:
            lines.append("…（后续省略）")
            break
        lines.append(line); total += len(line)

    try:
        from llm.llm_client import chat as _llm_chat
        raw = _llm_chat(
            _SUMMARY_PROMPT.format(thread="\n".join(lines)),
            temperature=0.2,
            system="简明、结构化、保留责任人@名",
        )
    except Exception as e:
        logger.warning("summarize_discussion llm fail: %s", e)
        raw = ""

    return {"raw": raw, **_parse_summary(raw)}


def _parse_summary(raw: str) -> Dict[str, str]:
    def _slice(label: str) -> str:
        m = re.search(rf"{label}[^\n]*\n(.+?)(?=\n\d+\.|$)", raw, re.S)
        return (m.group(1).strip() if m else "").strip() or "无"
    return {
        "decisions": _slice("决议"),
        "actions": _slice("行动项"),
        "questions": _slice("开放问题"),
    }


# ── Recommend next steps ──────────────────────────────────────────────────────


def recommend_next_steps(plan_summary: Dict[str, Any],
                         *, user_open_id: str = "",
                         max_suggestions: int = 3) -> List[str]:
    """Return a short list of recommended follow-up intents.

    Strategy:
    1. Pull the last ~10 plan outcomes from MemoryLayer (Mem0g recall).
    2. Ask the LLM to propose next-step intents grounded in LARKMENTOR.md.
    3. De-dup against the current plan's deliverables.
    """
    try:
        from core.agent_pilot.harness import default_memory
        mem = default_memory()
        recalled = (
            mem.recall(f"next steps for user {user_open_id}", user_id=user_open_id, k=8)
            if user_open_id else []
        )
    except Exception:
        recalled = []

    deliv = ", ".join((d.get("label", "") for d in plan_summary.get("deliverables") or []))
    sys_prompt = (
        "你是 LarkMentor 的下一步推荐器。基于用户 LARKMENTOR.md 风格与最近记忆，"
        "只输出 3 条下一步建议，每条 ≤ 20 字，不编号、换行分隔、不要解释。"
    )
    user_prompt = (
        f"刚完成的 Plan 意图：{plan_summary.get('intent','')}\n"
        f"已产出：{deliv or '无'}\n"
        f"最近记忆：{'; '.join(getattr(m, 'content', str(m))[:60] for m in recalled[:6]) or '无'}"
    )
    try:
        from llm.llm_client import chat as _llm_chat
        raw = _llm_chat(user_prompt, temperature=0.4, system=sys_prompt)
    except Exception as e:
        logger.warning("recommend_next_steps llm fail: %s", e)
        return []

    lines = [ln.strip("·-•· ").strip() for ln in (raw or "").splitlines() if ln.strip()]
    seen = set(); out = []
    for ln in lines:
        if ln and ln not in seen:
            seen.add(ln); out.append(ln)
        if len(out) >= max_suggestions:
            break
    return out
