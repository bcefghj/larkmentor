"""5 闸门意图识别（V1.5 重写版）.

设计动机（来自 V1 → V1.5 的批判）:
  - V1 的 3 闸门 + NOT_INTENT 兜底 → 大量轻量寒暄被 bot 沉默 → 用户首条体验差。
  - V1 把"显式 /pilot"和"关键字命中"混在一起 → 难以独立调优 cooldown。
  - 复杂度的根源是命中信号不分层；V1.5 显式拆 5 闸门：

      闸门 1 命令 (help/status/我来执行/暂停/继续/忽略)
      闸门 2 显式触发 (/pilot @pilot 前缀)
      闸门 3 关键字快速通道 (强 form 词单独 / 弱 form 词 + 动词)
      闸门 4 LLM 判定 (MiniMax-M2.7-highspeed JSON 输出，外部注入；本模块不依赖 LLM client)
      闸门 5 闲聊兜底 (greeting / LLM verdict=chat → AI 友好回复，绝不沉默)

  - LLM 判定通过 `Callable[[str, list[ChatMessage]], Awaitable[LLMJudgement]]` 注入，
    本模块不直接 import pilot.llm.client，方便测试 + 解耦。

  - PRD §问题 5（混合机制）：规则层 + LLM 层；任一闸门命中即返。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable

logger = logging.getLogger("pilot.runtime.intent")


class IntentVerdict(str, Enum):
    NOT_INTENT = "not_intent"          # 空消息或纯符号
    CHAT = "chat"                      # V1.5 新增：闲聊 → AI 友好回复
    COMMAND = "command"                # 帮助 / 状态 / 我来执行
    NEEDS_CLARIFY = "needs_clarify"    # 是任务但信息不足
    READY = "ready"                    # 直接执行
    COOLDOWN = "cooldown"              # 主题在 cooldown 内静默
    IGNORED = "ignored"                # 用户标记忽略


class CommandKind(str, Enum):
    HELP = "help"
    STATUS = "status"
    CLAIM = "claim"
    PAUSE = "pause"
    RESUME = "resume"
    IGNORE = "ignore"


@dataclass
class LLMJudgement:
    """闸门 4 的 LLM 输出（结构化 JSON 反序列化结果）.

    保留 V1 字段（is_task/task_type/goal/resources/next_step/confidence）以兼容老测试，
    新增 V1.5 字段（verdict/summary/missing/friendly_reply/needs_web_search）。
    """

    verdict: str = "not_intent"        # ready | chat | clarify | not_intent
    is_task: bool = False
    task_type: str = ""                # doc | ppt | canvas | trio | none
    goal: str = ""
    resources: list[str] = field(default_factory=list)
    next_step: str = ""
    summary: str = ""                  # 任务一句话归纳，<=20 字
    missing: list[str] = field(default_factory=list)  # ['audience','form','goal','time']
    friendly_reply: str = ""           # CHAT 时的友好回复 <=40 字
    needs_web_search: bool = False
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
    chat_reply: str = ""
    needs_web_search: bool = False
    command_kind: str = ""
    raw_text: str = ""

    def is_actionable(self) -> bool:
        return self.verdict not in (IntentVerdict.NOT_INTENT, IntentVerdict.COOLDOWN, IntentVerdict.IGNORED)


@dataclass
class ChatMessage:
    sender_open_id: str
    text: str
    chat_id: str = ""
    msg_id: str = ""
    ts: int = 0


# ── 字典（PRD §问题 5 + 飞书 Bot 实战经验 + 真实语料）─────────────────────────


STRONG_FORM_WORDS = (
    "三件套", "PPT", "ppt", "Ppt", "幻灯", "白板", "画布",
    "架构图", "流程图", "思维导图", "脑图", "演示稿", "演示文稿",
    "文档", "报告", "方案", "PRD", "需求文档", "策划方案",
)

WEAK_FORM_WORDS = (
    "汇报", "介绍", "分析", "调研", "研究", "复盘", "总结",
    "纪要", "周报", "月报", "日报", "盘点", "概览", "策划",
)

VERB_WORDS = (
    "写", "做", "做个", "做一份", "出个", "出一份", "生成", "整理", "整理一下",
    "汇总", "汇总一下", "梳理", "拉齐", "画", "搞", "弄", "出", "出一版",
    "形成", "沉淀", "沉淀一下", "准备",
)

GREETING_WORDS = (
    "你好", "您好", "Hi", "hi", "Hello", "hello", "Hey", "hey", "嗨", "哈喽",
    "在吗", "在不", "在么", "在嘛", "早", "晚安", "下午好", "上午好", "中午好",
    "辛苦", "辛苦了", "谢谢", "感谢", "Thanks", "thanks", "Thx", "thx",
    "OK", "ok", "好的", "收到", "嗯", "嗯嗯", "嗯哼",
)

COMMAND_WORDS: dict[str, CommandKind] = {
    "帮助": CommandKind.HELP,
    "/help": CommandKind.HELP,
    "help": CommandKind.HELP,
    "Help": CommandKind.HELP,
    "状态": CommandKind.STATUS,
    "/status": CommandKind.STATUS,
    "status": CommandKind.STATUS,
    "我来执行": CommandKind.CLAIM,
    "认领": CommandKind.CLAIM,
    "暂停": CommandKind.PAUSE,
    "继续": CommandKind.RESUME,
    "忽略": CommandKind.IGNORE,
    "不用了": CommandKind.IGNORE,
}

EXPLICIT_PREFIXES = ("/pilot", "@pilot")

TIMELY_RE = re.compile(
    r"(最新|当前|近期|最近|本周|本月|今日|今年|去年|"
    r"2026|2025|2024|今天|昨天|前天|刚才)"
)

TASK_SEMANTIC_PATTERNS = (
    re.compile(r"(帮|麻烦|需要).{0,8}(写|做|生成|整理|汇总|画|画一)"),
    re.compile(r"(下周|这周|明天|后天).{0,8}(汇报|展示|讲|发|给)"),
    re.compile(r"(我们|大家).{0,6}(对齐|讨论|沟通).{0,2}(下|一下)"),
)


# ── Cooldown ──────────────────────────────────────────────────────────────


class CooldownStore:
    """主题 + 会话维度的 cooldown：群聊 5min、单聊 10s."""

    def __init__(self, *, group_cooldown_sec: int = 300, p2p_cooldown_sec: int = 10) -> None:
        self.group_cooldown_sec = group_cooldown_sec
        self.p2p_cooldown_sec = p2p_cooldown_sec
        self._fired: dict[str, float] = {}
        self._ignored: set[str] = set()

    @staticmethod
    def _key(chat_id: str, theme: str) -> str:
        return f"{chat_id}::{theme}"

    def is_cooldown(self, chat_id: str, theme: str, *, is_p2p: bool = False) -> bool:
        key = self._key(chat_id, theme)
        if key in self._ignored:
            return True
        last = self._fired.get(key, 0.0)
        cooldown = self.p2p_cooldown_sec if is_p2p else self.group_cooldown_sec
        return (time.time() - last) < cooldown

    def mark_fired(self, chat_id: str, theme: str) -> None:
        self._fired[self._key(chat_id, theme)] = time.time()

    def mark_ignored(self, chat_id: str, theme: str) -> None:
        self._ignored.add(self._key(chat_id, theme))


# ── helpers ────────────────────────────────────────────────────────────────


def _detect_command(text: str) -> CommandKind | None:
    """命令检测：纯命令词、/pilot 前缀的命令词、status/help 别名都算。"""
    norm = text.strip()
    if not norm:
        return None
    # /pilot 帮助 / @pilot 状态 → 去前缀再匹配
    lower = norm.lower()
    for prefix in EXPLICIT_PREFIXES:
        if lower.startswith(prefix):
            stripped = norm[len(prefix):].lstrip(" ：:、,").strip()
            if stripped and stripped in COMMAND_WORDS:
                return COMMAND_WORDS[stripped]
            if stripped and stripped.lower() in COMMAND_WORDS:
                return COMMAND_WORDS[stripped.lower()]
            break
    if norm in COMMAND_WORDS:
        return COMMAND_WORDS[norm]
    return COMMAND_WORDS.get(norm.lower())


def _detect_explicit(text: str) -> bool:
    lower = text.lstrip().lower()
    return any(lower.startswith(p) for p in EXPLICIT_PREFIXES)


def _detect_keywords(text: str) -> tuple[list[str], bool, bool, bool]:
    """返回 (rule_hits, has_strong_form, has_weak_form, has_verb)."""
    hits: list[str] = []
    has_strong = False
    has_weak = False
    has_verb = False
    lower = text.lower()
    for kw in STRONG_FORM_WORDS:
        if kw.lower() in lower:
            hits.append(f"form_strong:{kw}")
            has_strong = True
            break
    if not has_strong:
        for kw in WEAK_FORM_WORDS:
            if kw in text:
                hits.append(f"form_weak:{kw}")
                has_weak = True
                break
    for kw in VERB_WORDS:
        if kw in text:
            hits.append(f"verb:{kw}")
            has_verb = True
            break
    for pat in TASK_SEMANTIC_PATTERNS:
        if pat.search(text):
            hits.append(f"semantic:{pat.pattern[:24]}")
    return hits, has_strong, has_weak, has_verb


def _detect_greeting(text: str) -> bool:
    norm = text.strip()
    if not norm or len(norm) > 20:
        return False
    for kw in GREETING_WORDS:
        if norm == kw or norm.lower() == kw.lower():
            return True
    if len(norm) <= 8:
        for kw in GREETING_WORDS[:8]:
            if kw.lower() in norm.lower():
                return True
    return False


def _detect_timely(text: str) -> bool:
    return bool(TIMELY_RE.search(text))


# 占位/客气/语气词（信息充分性判定时剥离）
FILLER_WORDS = (
    "帮我", "帮忙", "帮", "麻烦", "请", "给我", "能不能", "可以",
    "一下", "下", "一份", "一版", "份", "版", "我", "你", "他",
    "的", "了", "吧", "呢", "啊", "嘛", "哦",
)


def _has_topic(text: str) -> bool:
    """判定是否信息充分到可直接 READY，避免 form 词单出导致空启 plan.

    策略：剥离 form/verb/filler 后剩余 ≥ 3 字符；或命中明显主题模式 / 时效词 / 长度阈值。
    """
    if _detect_timely(text):
        return True
    if re.search(r"(关于|对|针对|围绕)([^，。,;\s]{2,})", text):
        return True
    residual = text
    for kw in (*STRONG_FORM_WORDS, *WEAK_FORM_WORDS, *VERB_WORDS, *FILLER_WORDS):
        residual = residual.replace(kw, "")
    residual = re.sub(r"[，。、,.;;:?？!！\s]+", "", residual)
    if len(residual) >= 2:
        return True
    return len(text) >= 12


def _extract_theme(text: str) -> str:
    m = re.search(r"(关于|对|针对)([^，。,;\s]{2,16})", text)
    if m:
        return m.group(2)
    return text.strip()[:16]


def _default_chat_reply(text: str) -> str:
    norm = text.strip().lower()
    if any(w in norm for w in ("你好", "hi", "hello", "嗨", "hey", "哈喽")):
        return "你好！我是 Agent-Pilot，可以帮你写文档/做 PPT/画架构图。发`帮助`看示例 ✨"
    if any(w in norm for w in ("谢谢", "感谢", "thanks", "thx", "辛苦")):
        return "不客气，需要帮你做什么尽管说～"
    if any(w in norm for w in ("收到", "好的", "ok", "嗯", "知道了")):
        return "👌 随时叫我"
    return "我在哦，需要我做点什么？发`帮助`看示例，比如「OpenClaw 三件套」「做 8 页 PPT 关于 X」"


def _build_clarify_questions(missing: list[str]) -> list[str]:
    mapping = {
        "audience": "这份产出主要是给谁看？（上级 / 同事 / 客户）",
        "form": "希望生成什么类型？（文档 / PPT / 文档+PPT 三件套）",
        "goal": "这个任务的核心目标是什么？",
        "time": "希望多长时间内完成？",
    }
    questions = [mapping[m] for m in missing if m in mapping]
    if not questions:
        questions = [
            "希望生成什么类型？（文档 / PPT / 文档+PPT 三件套）",
            "这份产出主要是给谁看？（上级 / 同事 / 客户）",
            "希望多长时间内完成？",
        ]
    return questions


# ── 主 Router ──────────────────────────────────────────────────────────────


LLMJudgeFn = Callable[[str, list[ChatMessage]], Awaitable[LLMJudgement]]


class IntentRouter:
    """5 闸门意图识别器."""

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

    async def detect(
        self,
        history: list[ChatMessage],
        *,
        is_p2p: bool = True,
    ) -> IntentResult:
        if not history:
            return IntentResult(verdict=IntentVerdict.NOT_INTENT)

        msg = history[-1]
        text = (msg.text or "").strip()
        if not text:
            return IntentResult(verdict=IntentVerdict.NOT_INTENT, raw_text="")

        # ── 闸门 1：命令 ──
        cmd = _detect_command(text)
        if cmd is not None:
            return IntentResult(
                verdict=IntentVerdict.COMMAND,
                rule_hits=[f"cmd:{cmd.value}"],
                command_kind=cmd.value,
                raw_text=text[:80],
                suggested_owner=msg.sender_open_id,
            )

        # ── 闸门 2：显式 ──
        if _detect_explicit(text):
            return IntentResult(
                verdict=IntentVerdict.READY,
                rule_hits=["explicit_pilot"],
                theme_key=_extract_theme(text),
                suggested_owner=msg.sender_open_id,
                suggested_title=text[:40],
                needs_web_search=_detect_timely(text),
                raw_text=text[:200],
            )

        # ── 闸门 3：关键字快速通道（短路 READY，仅当信号强且信息充分）──
        hits, has_strong, has_weak, has_verb = _detect_keywords(text)
        keyword_hit = has_strong or (has_weak and has_verb)
        info_rich = _has_topic(text)

        if keyword_hit and info_rich:
            theme = _extract_theme(text)
            if self.cooldown.is_cooldown(msg.chat_id, theme, is_p2p=is_p2p):
                return IntentResult(
                    verdict=IntentVerdict.COOLDOWN,
                    theme_key=theme,
                    rule_hits=hits,
                )
            self.cooldown.mark_fired(msg.chat_id, theme)
            return IntentResult(
                verdict=IntentVerdict.READY,
                rule_hits=hits + ["info_rich"],
                theme_key=theme,
                suggested_owner=msg.sender_open_id,
                suggested_title=text[:40],
                needs_web_search=_detect_timely(text),
                raw_text=text[:200],
            )

        # ── 闸门 4：LLM 判定 ──
        recent = history[-self.recent_window:]
        judgement: LLMJudgement | None = None
        if self.llm_judge is not None:
            try:
                judgement = await self.llm_judge(text, recent)
            except Exception as e:
                logger.warning("LLM judge failed, fallback: %s", e)
                judgement = None

        if judgement is not None:
            verdict_str = (judgement.verdict or "").lower()
            if verdict_str == "ready" or (judgement.is_task and not judgement.missing):
                return IntentResult(
                    verdict=IntentVerdict.READY,
                    rule_hits=hits + ["llm_ready"],
                    theme_key=_extract_theme(text),
                    suggested_owner=msg.sender_open_id,
                    suggested_title=judgement.summary or text[:40],
                    llm_judgement=judgement,
                    needs_web_search=judgement.needs_web_search or _detect_timely(text),
                    raw_text=text[:200],
                )
            if verdict_str == "clarify" or (judgement.is_task and judgement.missing):
                clarify_q = _build_clarify_questions(judgement.missing or ["form", "audience"])
                return IntentResult(
                    verdict=IntentVerdict.NEEDS_CLARIFY,
                    rule_hits=hits + ["llm_clarify"],
                    theme_key=_extract_theme(text),
                    suggested_owner=msg.sender_open_id,
                    suggested_title=judgement.summary or text[:40],
                    clarify_questions=clarify_q,
                    llm_judgement=judgement,
                    raw_text=text[:200],
                )
            if verdict_str == "chat":
                return IntentResult(
                    verdict=IntentVerdict.CHAT,
                    rule_hits=hits + ["llm_chat"],
                    chat_reply=judgement.friendly_reply or _default_chat_reply(text),
                    llm_judgement=judgement,
                    raw_text=text[:200],
                )
            # 其他/timeout 走兜底

        # ── 闸门 5：兜底 ──
        if has_weak and not has_verb:
            theme = _extract_theme(text)
            if self.cooldown.is_cooldown(msg.chat_id, theme, is_p2p=is_p2p):
                return IntentResult(
                    verdict=IntentVerdict.COOLDOWN,
                    theme_key=theme,
                    rule_hits=hits,
                )
            self.cooldown.mark_fired(msg.chat_id, theme)
            return IntentResult(
                verdict=IntentVerdict.NEEDS_CLARIFY,
                rule_hits=hits,
                theme_key=theme,
                suggested_owner=msg.sender_open_id,
                suggested_title=text[:40],
                clarify_questions=_build_clarify_questions(["form", "audience", "time"]),
                raw_text=text[:200],
            )

        # 显式 form/verb 命中但没有 LLM 判定（V1 兼容场景）
        if (has_strong or has_weak or has_verb) and self.llm_judge is None:
            theme = _extract_theme(text)
            return IntentResult(
                verdict=IntentVerdict.NEEDS_CLARIFY,
                rule_hits=hits,
                theme_key=theme,
                suggested_owner=msg.sender_open_id,
                suggested_title=text[:40],
                clarify_questions=_build_clarify_questions(["audience", "form", "time"]),
                raw_text=text[:200],
            )

        if _detect_greeting(text):
            return IntentResult(
                verdict=IntentVerdict.CHAT,
                rule_hits=hits + ["greeting"],
                chat_reply=_default_chat_reply(text),
                raw_text=text[:200],
            )

        if any(h.startswith("semantic:") for h in hits):
            return IntentResult(
                verdict=IntentVerdict.CHAT,
                rule_hits=hits,
                chat_reply=_default_chat_reply(text),
                raw_text=text[:200],
            )

        # 真没识别到任何信号 → 仍然不沉默：返回 CHAT 友好引导
        return IntentResult(
            verdict=IntentVerdict.CHAT,
            rule_hits=hits,
            chat_reply=_default_chat_reply(text),
            raw_text=text[:200],
        )
