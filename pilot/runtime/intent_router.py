"""三闸门意图识别（Anthropic Routing 模式 · PRD §问题 5）.

闸门 1: 规则层（关键词 + 任务语义 + 上下文条件）
闸门 2: LLM 层（结构化判断 task_type / goal / resources / next_step）
闸门 3: 最小信息（具备 task + 输出形态 + 受众）

只有 3 闸全过 → READY；
2 过 1 缺 → NEEDS_CLARIFY；
1 不过 → NOT_INTENT。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

logger = logging.getLogger("pilot.runtime.intent")


# ── 数据结构 ────────────────────────────────────────────────────────────────


class IntentVerdict(str, Enum):
    NOT_INTENT = "not_intent"
    COOLDOWN = "cooldown"
    IGNORED = "ignored"
    NEEDS_CLARIFY = "needs_clarify"
    READY = "ready"


@dataclass
class LLMJudgement:
    is_task: bool = False
    task_type: str = ""
    goal: str = ""
    resources: list[str] = field(default_factory=list)
    next_step: str = ""
    confidence: float = 0.0


@dataclass
class IntentResult:
    verdict: IntentVerdict
    rule_hits: list[str] = field(default_factory=list)
    theme_key: str = ""
    suggested_owner: str = ""
    suggested_title: str = ""
    clarify_questions: list[str] = field(default_factory=list)
    llm_judgement: LLMJudgement | None = None
    raw_text: str = ""


@dataclass
class ChatMessage:
    sender_open_id: str
    text: str
    chat_id: str = ""
    msg_id: str = ""
    ts: int = 0


# ── 规则层 ──────────────────────────────────────────────────────────────────


# 关键词命中（PRD §问题 5）
EXPLICIT_KEYWORDS = [
    "整理一下", "汇总一下", "做个方案", "出个文档", "生成 PPT", "做个 PPT",
    "下周汇报", "给老板看", "拉齐一下", "沉淀一下", "形成材料",
    "写个大纲", "做个复盘", "输出版本", "发一版", "准备演示",
    "方案", "复盘", "周报", "月报", "PRD", "需求文档",
    "架构图", "流程图", "白板", "画布",
    "@pilot", "/pilot",
]

# 任务语义命中（意图）
TASK_SEMANTIC_PATTERNS = [
    r"(帮|麻烦|需要).*(写|做|生成|整理|汇总|画|画一)",
    r"(下周|这周|明天|后天).*(汇报|展示|讲|发|给)",
    r"(我们|大家).*(对齐|讨论|沟通).*(下|一下)",
]


def _detect_rules(text: str) -> tuple[list[str], str]:
    hits: list[str] = []
    for kw in EXPLICIT_KEYWORDS:
        if kw.lower() in text.lower():
            hits.append(f"kw:{kw}")
    for pat in TASK_SEMANTIC_PATTERNS:
        if re.search(pat, text):
            hits.append(f"semantic:{pat[:20]}")

    theme = ""
    m = re.search(r"(关于|对|针对)([^，。,;\s]{2,16})", text)
    if m:
        theme = m.group(2)
    elif text:
        theme = text[:16]
    return hits, theme


# ── 上下文 cooldown（避免群聊里频繁弹卡片）─────────────────────────────────


class CooldownStore:
    """轻量内存 cooldown：theme_key + chat_id → 最近触发时间."""

    def __init__(self, *, cooldown_sec: int = 300) -> None:
        self.cooldown_sec = cooldown_sec
        self._fired: dict[str, float] = {}
        self._ignored: set[str] = set()

    def is_cooldown(self, chat_id: str, theme: str) -> bool:
        key = f"{chat_id}::{theme}"
        if key in self._ignored:
            return True
        last = self._fired.get(key, 0.0)
        return (time.time() - last) < self.cooldown_sec

    def mark_fired(self, chat_id: str, theme: str) -> None:
        self._fired[f"{chat_id}::{theme}"] = time.time()

    def mark_ignored(self, chat_id: str, theme: str) -> None:
        self._ignored.add(f"{chat_id}::{theme}")


# ── 主 router ───────────────────────────────────────────────────────────────


# LLM 闸门函数签名: 接收 (text, history) → LLMJudgement
LLMJudgeFn = Callable[[str, list[ChatMessage]], Awaitable[LLMJudgement]]


class IntentRouter:
    """三闸门意图识别."""

    def __init__(
        self,
        *,
        llm_judge: LLMJudgeFn | None = None,
        cooldown: CooldownStore | None = None,
        recent_window: int = 20,
    ) -> None:
        self.llm_judge = llm_judge
        self.cooldown = cooldown or CooldownStore()
        self.recent_window = recent_window

    async def detect(self, history: list[ChatMessage]) -> IntentResult:
        """对最新一条消息做三闸门判断."""
        if not history:
            return IntentResult(verdict=IntentVerdict.NOT_INTENT)

        msg = history[-1]
        text = msg.text or ""

        # 显式触发优先
        if text.lstrip().lower().startswith(("/pilot", "@pilot")):
            return IntentResult(
                verdict=IntentVerdict.READY,
                rule_hits=["explicit_pilot"],
                theme_key=text[:24],
                suggested_owner=msg.sender_open_id,
                suggested_title=text[:40],
            )

        # 闸门 1: 规则
        hits, theme = _detect_rules(text)
        if not hits:
            return IntentResult(verdict=IntentVerdict.NOT_INTENT, raw_text=text[:80])

        # cooldown
        if self.cooldown.is_cooldown(msg.chat_id, theme):
            return IntentResult(verdict=IntentVerdict.COOLDOWN, theme_key=theme, rule_hits=hits)

        # 上下文条件：最近 5-20 条同主题、>=2 人参与
        recent = history[-self.recent_window:]
        unique_senders = {m.sender_open_id for m in recent if m.text}
        if len(recent) < 2 and len(unique_senders) < 2 and "explicit_pilot" not in hits:
            # 单聊场景下放宽：至少有 1 人 + 1 句即可
            if len(recent) < 1:
                return IntentResult(verdict=IntentVerdict.NOT_INTENT, rule_hits=hits, raw_text=text[:80])

        # 闸门 2: LLM
        judgement: LLMJudgement | None = None
        if self.llm_judge is not None:
            try:
                judgement = await self.llm_judge(text, recent)
            except Exception as e:
                logger.warning("LLM judge failed, fall back to rule-only: %s", e)

        # 闸门 3: 最小信息（task_type + goal + 至少一项资源/受众/形态）
        result = IntentResult(
            rule_hits=hits,
            theme_key=theme,
            suggested_owner=msg.sender_open_id,
            suggested_title=text[:40],
            llm_judgement=judgement,
            raw_text=text[:200],
            verdict=IntentVerdict.NOT_INTENT,
        )
        if judgement is None:
            # 没 LLM 判断，规则命中视作 NEEDS_CLARIFY 保守处理
            result.verdict = IntentVerdict.NEEDS_CLARIFY
            result.clarify_questions = [
                "这份产出主要是给谁看？（上级 / 同事 / 客户）",
                "希望生成什么类型？（文档 / PPT / 文档+PPT）",
                "希望多长时间内完成？",
            ]
            return result

        if not judgement.is_task:
            result.verdict = IntentVerdict.NOT_INTENT
            return result

        # 最小信息检查
        has_goal = bool(judgement.goal and len(judgement.goal) >= 4)
        has_form = any(k in text for k in ("文档", "PPT", "ppt", "汇报", "画布", "白板", "演示", "方案"))
        has_audience = any(k in text for k in ("老板", "客户", "团队", "同事", "评委", "上级"))

        score = sum([has_goal, has_form, has_audience])
        if score >= 2:
            result.verdict = IntentVerdict.READY
        else:
            result.verdict = IntentVerdict.NEEDS_CLARIFY
            result.clarify_questions = []
            if not has_goal:
                result.clarify_questions.append("这个任务的核心目标是什么？")
            if not has_form:
                result.clarify_questions.append("希望生成什么类型？（文档 / PPT / 画布 / 三件套）")
            if not has_audience:
                result.clarify_questions.append("汇报对象是谁？（上级 / 同事 / 客户）")
            if not result.clarify_questions:
                result.clarify_questions = ["请补充任务关键信息"]

        return result
