"""IntentDetector · PRD §5 + Q5 主动识别（三闸门）.

闸门 1（规则层）—— 关键词命中 + 上下文信号
闸门 2（LLM 层）—— 让 LLM 结构化判断"是否真任务"+ 输出 task_type/goal/resources/next_step
闸门 3（最小信息）—— ContextPack.has_min_info() 必须为真，否则改为「澄清卡片」

附加：冷却（默认 60 分钟同主题不重复弹卡）+ 同主题合并 + per-chat 忽略列表

设计：
- 不依赖 LLM 也能跑出闸门 1 + 闸门 3 的合理结果（degraded mode）
- LLM judge 失败时降级为"规则强命中即触发"
- 6 级 Memory 通过 ``memory_resolver`` 注入 LLM system prompt（P15 阶段加深）
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("pilot.application.intent_detector")


# ── 关键词词典（PRD §5 + 问题 5 全示例 + 行业扩展） ──────────────────────────

# 中文办公关键词（hot path，规则层先筛）
KEYWORDS_OFFICE = {
    # 整理 / 沉淀
    "整理一下", "汇总一下", "梳理一下", "拉齐一下", "沉淀一下", "形成材料",
    # 文档 / 方案
    "做个方案", "出个文档", "起草", "做个计划书", "写个大纲", "PRD", "需求文档",
    # 演示 / 汇报
    "生成 PPT", "做 PPT", "做PPT", "做演示", "下周汇报", "给老板看", "写汇报",
    "评审", "做汇报", "准备演示", "演讲稿",
    # 复盘 / 季度
    "做个复盘", "复盘汇报", "季度复盘", "活动复盘", "周报", "月报",
    # 输出 / 发布
    "输出版本", "发一版", "出一版", "完结", "归档",
    # 英文常见
    "ppt", "deck", "presentation", "summary", "report", "proposal",
    "wrap up", "follow up",
}

# 任务语义动词（次要规则，用 substring 匹配，覆盖更广）
SEMANTIC_VERBS = (
    "汇报", "对外", "对上", "评审", "演示", "归档", "形成", "整理",
    "结构化", "对齐", "结论", "材料", "成果", "交付",
)

# 时间节点信号（提升任务真实性）
TIME_KEYWORDS = (
    "今天", "明天", "后天", "下周", "下下周", "本周", "本月", "下月",
    "周一", "周二", "周三", "周四", "周五", "deadline", "ddl",
)

# 资料引用信号（提升任务真实性）
RESOURCE_PATTERNS = (
    re.compile(r"https?://[^\s]+"),
    re.compile(r"飞书[文档|文件|文档|wiki|画板]"),
    re.compile(r"\.docx?|\.pptx?|\.xlsx?|\.pdf"),
)


# ── 数据结构 ────────────────────────────────────────────────────────────────


class IntentVerdict(str, Enum):
    """三闸门最终结论."""

    READY = "ready"               # 通过全部三闸门，应弹任务卡
    NEEDS_CLARIFY = "clarify"     # 通过闸门 1+2 但闸门 3 不达标，弹澄清卡
    NOT_INTENT = "not_intent"     # 闸门 1 或 2 不通过
    COOLDOWN = "cooldown"         # 闸门通过但被冷却拦截
    IGNORED = "ignored"           # 用户曾忽略此主题


@dataclass
class ChatMessage:
    """统一 IM 消息载体."""

    sender_open_id: str
    text: str
    chat_id: str = ""
    msg_id: str = ""
    ts: int = 0


@dataclass
class RuleHit:
    """闸门 1 命中证据."""

    keyword_hits: List[str] = field(default_factory=list)
    semantic_hits: List[str] = field(default_factory=list)
    has_time_signal: bool = False
    has_resource_signal: bool = False
    multi_speaker: bool = False
    consecutive_msgs: int = 0
    score: float = 0.0  # 0.0-1.0


@dataclass
class LLMJudgement:
    """闸门 2 LLM 结构化判断."""

    is_task: bool = False
    task_type: str = ""        # "report" / "doc" / "ppt" / "canvas" / "review" / ...
    goal: str = ""
    resources: List[str] = field(default_factory=list)
    next_step: str = ""
    confidence: float = 0.0    # 0.0-1.0
    raw_response: str = ""


@dataclass
class TaskCandidate:
    """识别结果（最终给上游 task_service.create_task）."""

    verdict: IntentVerdict
    rule_hit: RuleHit
    llm_judgement: Optional[LLMJudgement] = None
    suggested_title: str = ""
    suggested_owner: str = ""    # 通常是发言人 open_id
    chat_id: str = ""
    theme_key: str = ""          # 用于冷却合并
    clarify_questions: List[str] = field(default_factory=list)


# ── 闸门 1：规则层 ──────────────────────────────────────────────────────────


def detect_rules(messages: List[ChatMessage]) -> RuleHit:
    """对最新 N 条消息做规则检测.

    评分模型（rule layer score, 0.0-1.0）：
    - keyword 命中 +0.4 / 命中
    - semantic verb 命中 +0.15 / 命中
    - time signal +0.20
    - resource signal +0.15
    - multi-speaker +0.15
    - 连续消息数 >= 5 + 0.10

    上限 1.0。
    """
    if not messages:
        return RuleHit()

    # 检查最近 N 条消息的合并文本（不仅限于最后一条），覆盖
    # 「u1 提任务 → u2 附议 → u3 添加资料」这样的群聊真实场景
    LOOKBACK_N = 5
    recent = messages[-LOOKBACK_N:]
    text_concat = "\n".join(m.text for m in recent)
    text_lower = text_concat.lower()
    hit = RuleHit()

    # keyword
    for kw in KEYWORDS_OFFICE:
        if kw.lower() in text_lower:
            hit.keyword_hits.append(kw)

    # semantic verb
    for v in SEMANTIC_VERBS:
        if v in text_concat:
            hit.semantic_hits.append(v)

    # time
    for tw in TIME_KEYWORDS:
        if tw in text_lower:
            hit.has_time_signal = True
            break

    # resource
    for pat in RESOURCE_PATTERNS:
        if pat.search(text_concat):
            hit.has_resource_signal = True
            break

    # context: multi-speaker / consecutive
    senders = {m.sender_open_id for m in messages[-10:]}
    hit.multi_speaker = len(senders) >= 2
    hit.consecutive_msgs = len(messages[-20:])

    # score
    score = 0.0
    score += min(0.4 * len(hit.keyword_hits), 0.6)
    score += min(0.15 * len(hit.semantic_hits), 0.30)
    score += 0.20 if hit.has_time_signal else 0.0
    score += 0.15 if hit.has_resource_signal else 0.0
    score += 0.15 if hit.multi_speaker else 0.0
    score += 0.10 if hit.consecutive_msgs >= 5 else 0.0
    hit.score = min(score, 1.0)
    return hit


def rule_passes(hit: RuleHit, *, threshold: float = 0.40) -> bool:
    """闸门 1 通过条件：score >= threshold（默认 0.40）."""
    return hit.score >= threshold


# ── 闸门 2：LLM 层 ──────────────────────────────────────────────────────────


LLM_JUDGE_PROMPT = """你是一个企业 IM 中的任务识别助手。你需要判断给出的 IM 群聊片段
是否构成一个真实的、可推进的"办公协作任务"（比如要做的方案文档、汇报 PPT、
讨论复盘等）。

请只输出严格的 JSON（不要 markdown 围栏，不要解释），格式如下：

{
  "is_task": true|false,
  "task_type": "report|doc|ppt|canvas|review|brainstorm|other",
  "goal": "<一句话目标，10-30 字>",
  "resources": ["...资料类型 hints..."],
  "next_step": "<一句话建议>",
  "confidence": 0.0-1.0
}

判断标准（保守）：
- 需要 IM 中明确意图（例：要做 / 准备 / 汇报 / 复盘 / 给某人看 / 整理一下）
- 单纯打招呼、闲聊、技术问答不算任务
- 信息不足时 confidence 应低（< 0.5），但仍可标 is_task=true 让用户澄清

下面是 IM 片段：
"""


def _parse_llm_response(raw: str) -> LLMJudgement:
    """容错解析 LLM JSON。如果失败返回空 verdict."""
    j = LLMJudgement(raw_response=raw)
    if not raw or not raw.strip():
        return j
    # 提取首个 {} 块
    txt = raw.strip()
    # remove ```json ... ``` if present
    if txt.startswith("```"):
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", txt)
        if m:
            txt = m.group(1).strip()
    try:
        # 尝试整段
        data = json.loads(txt)
    except Exception:
        # 找首个 {...}
        m = re.search(r"\{[\s\S]*\}", txt)
        if not m:
            return j
        try:
            data = json.loads(m.group(0))
        except Exception:
            return j

    j.is_task = bool(data.get("is_task", False))
    j.task_type = str(data.get("task_type", "") or "")[:30]
    j.goal = str(data.get("goal", "") or "")[:200]
    res = data.get("resources", [])
    if isinstance(res, list):
        j.resources = [str(x)[:60] for x in res[:8]]
    j.next_step = str(data.get("next_step", "") or "")[:200]
    try:
        j.confidence = float(data.get("confidence", 0.0))
    except Exception:
        j.confidence = 0.0
    return j


# ``llm_caller`` is a function (messages_text) -> raw_response_str.
# Default uses ``llm.llm_client.chat`` if available; tests inject mock.
LLMCaller = Callable[[str], str]


def _default_llm_caller(im_text: str) -> str:
    """默认 LLM 调用：依赖现有 llm_client。失败返回空串.

    不强依赖：caller 可注入 mock，或在完全无 LLM 环境下返回空 → 启用降级路径。
    """
    try:
        from llm.llm_client import chat as _chat  # type: ignore[import-untyped]
    except Exception:
        return ""
    try:
        msgs = [
            {"role": "system", "content": LLM_JUDGE_PROMPT},
            {"role": "user", "content": im_text[:4000]},
        ]
        return _chat(messages=msgs, temperature=0.2, max_tokens=500) or ""
    except Exception as e:
        logger.debug("llm judge call failed: %s", e)
        return ""


def llm_judge(messages: List[ChatMessage], *,
              caller: Optional[LLMCaller] = None) -> LLMJudgement:
    """闸门 2 入口."""
    text = "\n".join(f"[{m.sender_open_id[-4:] or '??'}] {m.text}" for m in messages[-15:])
    raw = (caller or _default_llm_caller)(text)
    return _parse_llm_response(raw)


# ── 闸门 3：最小信息 + 冷却 + 忽略 ─────────────────────────────────────────


@dataclass
class CooldownEntry:
    chat_id: str
    theme_key: str
    fired_ts: int
    duration_sec: int


class CooldownManager:
    """同主题冷却 + 忽略列表（per-chat）."""

    def __init__(self, *, default_cooldown_sec: int = 3600) -> None:
        self._fired: Dict[Tuple[str, str], CooldownEntry] = {}
        self._ignored: Dict[Tuple[str, str], int] = {}
        self.default_cooldown_sec = default_cooldown_sec

    def _key(self, chat_id: str, theme: str) -> Tuple[str, str]:
        return (chat_id, _normalize_theme(theme))

    def is_cooling(self, chat_id: str, theme: str, *, now_ts: Optional[int] = None) -> bool:
        now = now_ts or int(time.time())
        ent = self._fired.get(self._key(chat_id, theme))
        if not ent:
            return False
        return (now - ent.fired_ts) < ent.duration_sec

    def is_ignored(self, chat_id: str, theme: str) -> bool:
        return self._key(chat_id, theme) in self._ignored

    def mark_fired(self, chat_id: str, theme: str, *,
                   duration_sec: Optional[int] = None,
                   now_ts: Optional[int] = None) -> None:
        ent = CooldownEntry(
            chat_id=chat_id, theme_key=_normalize_theme(theme),
            fired_ts=now_ts or int(time.time()),
            duration_sec=duration_sec or self.default_cooldown_sec,
        )
        self._fired[self._key(chat_id, theme)] = ent

    def mark_ignored(self, chat_id: str, theme: str) -> None:
        self._ignored[self._key(chat_id, theme)] = int(time.time())

    def reset(self) -> None:
        self._fired.clear()
        self._ignored.clear()


def _normalize_theme(theme: str) -> str:
    """主题规范化：去标点，转小写，前 24 字符."""
    if not theme:
        return ""
    s = re.sub(r"[\s\W_]+", "", theme.lower())
    return s[:24]


# ── 主入口 ──────────────────────────────────────────────────────────────────


@dataclass
class IntentDetectorConfig:
    rule_threshold: float = 0.40
    llm_min_confidence: float = 0.55
    llm_clarify_confidence: float = 0.30
    cooldown_sec: int = 3600
    enable_llm: bool = True


class IntentDetector:
    """三闸门主动识别器."""

    def __init__(self, *, config: Optional[IntentDetectorConfig] = None,
                 cooldown: Optional[CooldownManager] = None,
                 llm_caller: Optional[LLMCaller] = None) -> None:
        self.cfg = config or IntentDetectorConfig()
        self.cooldown = cooldown or CooldownManager(default_cooldown_sec=self.cfg.cooldown_sec)
        self.llm_caller = llm_caller or _default_llm_caller

    def detect(self, messages: List[ChatMessage]) -> TaskCandidate:
        """主入口：返回 TaskCandidate 包含 verdict 与全部证据."""
        if not messages:
            return TaskCandidate(verdict=IntentVerdict.NOT_INTENT, rule_hit=RuleHit())

        last = messages[-1]

        # 闸门 1
        hit = detect_rules(messages)
        if not rule_passes(hit, threshold=self.cfg.rule_threshold):
            return TaskCandidate(
                verdict=IntentVerdict.NOT_INTENT,
                rule_hit=hit,
                chat_id=last.chat_id,
            )

        # 闸门 2
        if self.cfg.enable_llm:
            try:
                jud = llm_judge(messages, caller=self.llm_caller)
            except Exception as e:
                logger.warning("llm_judge raised: %s", e)
                jud = LLMJudgement()
        else:
            jud = LLMJudgement(is_task=True, confidence=0.6, goal=last.text[:80])

        if not jud.is_task and self.cfg.enable_llm:
            return TaskCandidate(
                verdict=IntentVerdict.NOT_INTENT,
                rule_hit=hit, llm_judgement=jud,
                chat_id=last.chat_id,
            )

        theme = jud.goal or last.text[:24]

        # 冷却 / 忽略
        if self.cooldown.is_ignored(last.chat_id, theme):
            return TaskCandidate(
                verdict=IntentVerdict.IGNORED,
                rule_hit=hit, llm_judgement=jud,
                chat_id=last.chat_id, theme_key=theme,
            )
        if self.cooldown.is_cooling(last.chat_id, theme):
            return TaskCandidate(
                verdict=IntentVerdict.COOLDOWN,
                rule_hit=hit, llm_judgement=jud,
                chat_id=last.chat_id, theme_key=theme,
            )

        # 闸门 3：信息充分性
        if jud.confidence < self.cfg.llm_min_confidence or not jud.goal:
            qs = self._gen_clarify_questions(jud, hit, messages)
            return TaskCandidate(
                verdict=IntentVerdict.NEEDS_CLARIFY,
                rule_hit=hit, llm_judgement=jud,
                suggested_title=jud.goal or last.text[:30],
                suggested_owner=last.sender_open_id,
                chat_id=last.chat_id,
                theme_key=theme,
                clarify_questions=qs,
            )

        # 全部通过
        return TaskCandidate(
            verdict=IntentVerdict.READY,
            rule_hit=hit, llm_judgement=jud,
            suggested_title=jud.goal,
            suggested_owner=last.sender_open_id,
            chat_id=last.chat_id,
            theme_key=theme,
        )

    @staticmethod
    def _gen_clarify_questions(jud: LLMJudgement, hit: RuleHit,
                                messages: List[ChatMessage]) -> List[str]:
        """规则化生成 ≤2 个澄清问题（PRD §5 LLM 层信息不足分支）."""
        qs: List[str] = []
        if jud.task_type in ("report", "ppt") or "汇报" in (jud.goal or ""):
            qs.append("汇报对象是谁？（团队 / 部门 / 老板 / 客户）")
        if "ppt" not in jud.task_type and "doc" not in jud.task_type:
            qs.append("希望输出的是文档、PPT 还是自由画布？")
        if not hit.has_resource_signal:
            qs.append("是否需要引用已有资料（飞书 Wiki / 历史方案）？")
        return qs[:2]


__all__ = [
    "IntentDetector",
    "IntentDetectorConfig",
    "ChatMessage",
    "RuleHit",
    "LLMJudgement",
    "TaskCandidate",
    "IntentVerdict",
    "CooldownManager",
    "detect_rules",
    "rule_passes",
    "llm_judge",
]
