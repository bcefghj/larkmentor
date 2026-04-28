"""6-Dimension Message Classification Engine.

Each incoming message is scored on 6 orthogonal dimensions, each producing a
0..1 sub-score. The weighted sum maps to one of P0/P1/P2/P3.

Dimensions:
    1. identity      – who is the sender (VIP/superior/peer/...)
    2. relation      – how close is the relationship (frequency-based)
    3. content       – urgency/decision/question signals from text
    4. task_relation – relevance to user's current work_context
    5. time          – time-sensitivity patterns inside the message
    6. channel       – DM > project group > department > broadcast

Rule short-circuits:
    - whitelist hit → P0 immediately, score 1.0
    - explicit urgent keyword → score boosted to >= THRESHOLD_P0

Each classification produces a `ClassificationResult` with:
    - level (P0/P1/P2/P3)
    - score (float)
    - dimensions (dict of sub-scores) → enables explainable AI
    - reason (human-readable trace)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict, field
from typing import Dict, Optional

from config import Config
from core.sender_profile import SenderProfile, get_profile
from memory.user_state import UserState

logger = logging.getLogger("flowguard.classifier")


# ── Channel weights ──
CHANNEL_DM = 1.0
CHANNEL_SMALL_GROUP = 0.7  # ≤ 5 members
CHANNEL_PROJECT_GROUP = 0.6
CHANNEL_DEPARTMENT = 0.4
CHANNEL_BROADCAST = 0.15
CHANNEL_UNKNOWN = 0.4


# ── Content signal patterns ──
URGENT_PATTERNS = [
    r"紧急", r"urgent", r"ASAP", r"马上", r"立刻", r"立即",
    r"线上故障", r"P0", r"生产事故", r"严重\s*bug", r"阻塞",
    r"immediately", r"critical", r"blocking", r"事故", r"宕机", r"挂了",
]

DECISION_PATTERNS = [
    r"决定", r"批准", r"通过", r"拒绝", r"确认",
    r"approve", r"reject", r"confirm", r"decide", r"sign[- ]?off",
]

QUESTION_PATTERNS = [
    r"\?", r"？", r"怎么", r"如何", r"为什么", r"是不是", r"能否",
    r"可以吗", r"行吗", r"how to", r"why ", r"can you",
]

CHITCHAT_PATTERNS = [
    r"哈哈", r"嘿嘿", r"早", r"晚安", r"午饭", r"奶茶", r"好的",
    r"收到$", r"^OK", r"thx", r"thanks", r"嗯嗯",
]


@dataclass
class ClassificationResult:
    level: str
    score: float
    dimensions: Dict[str, float] = field(default_factory=dict)
    reason: str = ""
    auto_reply: str = ""
    used_llm: bool = False
    short_circuit: Optional[str] = None  # "whitelist" / "urgent_keyword" / None

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Dimension 1: Identity ────────────────────────────────────────

def score_identity(sender_profile: SenderProfile) -> float:
    return sender_profile.identity_score()


# ─── Dimension 2: Relation strength ──────────────────────────────

def score_relation(sender_profile: SenderProfile) -> float:
    return sender_profile.relation_strength()


# ─── Dimension 3: Content signals ─────────────────────────────────

def score_content(text: str) -> float:
    if not text:
        return 0.05
    t = text.lower()
    for pat in URGENT_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return 0.95
    score = 0.30
    decision_hit = False
    for pat in DECISION_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            score = max(score, 0.75)
            decision_hit = True
    question_hit = False
    for pat in QUESTION_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            score = max(score, 0.55)
            question_hit = True
    chitchat_hit = False
    for pat in CHITCHAT_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            chitchat_hit = True
    if chitchat_hit and not decision_hit and not question_hit:
        score = 0.10
    if len(text) > 200:
        score = max(score, 0.50)
    if len(text) < 5 and not decision_hit and not question_hit:
        score = min(score, 0.10)
    return score


# ─── Dimension 4: Task relation ───────────────────────────────────

def _keyword_overlap(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    set_a = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", a.lower()))
    set_b = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", b.lower()))
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def score_task_relation(message_text: str, user_context: str, task_names) -> float:
    """Estimate how related the message is to user's current task."""
    if not user_context and not task_names:
        return 0.3
    score = _keyword_overlap(message_text, user_context) * 1.5
    for task in task_names or []:
        score = max(score, _keyword_overlap(message_text, task) * 1.2)
    return min(1.0, score)


# ─── Dimension 5: Time sensitivity ────────────────────────────────

def score_time(text: str) -> float:
    if not text:
        return 0.15
    t = text.lower()
    for pat in Config.TIME_SENSITIVITY_PATTERNS:
        if pat.lower() in t:
            return 0.95
    if re.search(r"\d{1,2}\s*[:.]\s*\d{2}", text):
        return 0.6
    if re.search(r"\d+\s*分钟", text) or re.search(r"\d+\s*小时", text):
        return 0.7
    return 0.15


# ─── Dimension 6: Channel ─────────────────────────────────────────

def score_channel(chat_type: str, member_count: Optional[int] = None) -> float:
    if chat_type == "p2p":
        return CHANNEL_DM
    if chat_type == "group":
        if member_count is None:
            return CHANNEL_PROJECT_GROUP
        if member_count <= 5:
            return CHANNEL_SMALL_GROUP
        if member_count <= 30:
            return CHANNEL_PROJECT_GROUP
        if member_count <= 100:
            return CHANNEL_DEPARTMENT
        return CHANNEL_BROADCAST
    return CHANNEL_UNKNOWN


# ─── Main classifier ──────────────────────────────────────────────

def _contains_urgent_keyword(text: str) -> bool:
    lower = text.lower()
    return any(kw.lower() in lower for kw in Config.URGENT_KEYWORDS)


def classify(
    user: UserState,
    sender_profile: SenderProfile,
    message_text: str,
    chat_type: str = "p2p",
    chat_name: str = "",
    member_count: Optional[int] = None,
) -> ClassificationResult:
    """Run the 6-dimension classifier deterministically (no LLM needed)."""

    # Short-circuit 1: whitelist
    if sender_profile.name in user.whitelist or sender_profile.sender_id in user.whitelist:
        return ClassificationResult(
            level="P0",
            score=1.0,
            dimensions={"identity": 1.0, "shortcircuit": 1.0},
            reason=f"{sender_profile.name or sender_profile.sender_id} 在白名单中",
            short_circuit="whitelist",
        )

    # Short-circuit 2: explicit urgent keyword
    if _contains_urgent_keyword(message_text):
        return ClassificationResult(
            level="P0",
            score=Config.THRESHOLD_P0,
            dimensions={"content": 1.0, "shortcircuit": 1.0},
            reason="消息包含紧急关键词",
            short_circuit="urgent_keyword",
        )

    # Compute 6 dimensions
    d_identity = score_identity(sender_profile)
    d_relation = score_relation(sender_profile)
    d_content = score_content(message_text)
    task_names = [t.name for t in (user.tasks or [])]
    d_task = score_task_relation(message_text, user.work_context, task_names)
    d_time = score_time(message_text)
    d_channel = score_channel(chat_type, member_count)

    score = (
        d_identity * Config.DIM_WEIGHT_IDENTITY
        + d_relation * Config.DIM_WEIGHT_RELATION
        + d_content * Config.DIM_WEIGHT_CONTENT
        + d_task * Config.DIM_WEIGHT_TASK_REL
        + d_time * Config.DIM_WEIGHT_TIME
        + d_channel * Config.DIM_WEIGHT_CHANNEL
    )

    # Composite boosts
    if d_time >= 0.85 and (d_content >= 0.55 or d_identity >= 0.85):
        score = max(score, 0.65)
    if d_identity >= 0.85 and d_channel >= 0.9:
        score = max(score, 0.60)
    if d_content >= 0.7 and d_identity >= 0.85:  # superior + decision/urgent
        score = max(score, 0.60)

    # Composite damping
    # Broadcast/large-group + chitchat content + low-identity sender → squelch
    if d_channel <= 0.2 and d_content <= 0.30 and d_identity <= 0.30:
        score = min(score, 0.18)
    # Chitchat content (very low) in any non-DM context → squelch toward P3
    if d_content <= 0.12 and d_channel < 1.0:
        score = min(score, 0.20)
    # Superior in big broadcast + chitchat → P2 not P0
    if d_channel <= 0.2 and d_content <= 0.30:
        score = min(score, 0.30)
    # Bot sender + low content → P3
    if sender_profile.identity_tag == "bot" and d_content <= 0.55:
        score = min(score, 0.18)
    # Big group / broadcast (channel <= 0.4) + low content + non-superior + no time
    if (d_channel <= 0.4 and d_content <= 0.45 and d_identity <= 0.55
            and d_time <= 0.30 and d_task <= 0.30):
        score = min(score, 0.20)

    # Apply user-feedback bias
    score = max(0.0, min(1.0, score + sender_profile.importance_bias()))

    if score >= Config.THRESHOLD_P0:
        level = "P0"
    elif score >= Config.THRESHOLD_P1:
        level = "P1"
    elif score >= Config.THRESHOLD_P2:
        level = "P2"
    else:
        level = "P3"

    reason = (
        f"6维评分 {score:.2f}: "
        f"身份{d_identity:.2f}/关系{d_relation:.2f}/内容{d_content:.2f}/"
        f"任务{d_task:.2f}/时间{d_time:.2f}/频道{d_channel:.2f}"
    )
    if sender_profile.importance_bias() != 0:
        reason += f" + 用户反馈偏置{sender_profile.importance_bias():+.2f}"

    return ClassificationResult(
        level=level,
        score=score,
        dimensions={
            "identity": round(d_identity, 3),
            "relation": round(d_relation, 3),
            "content": round(d_content, 3),
            "task_relation": round(d_task, 3),
            "time": round(d_time, 3),
            "channel": round(d_channel, 3),
        },
        reason=reason,
    )


def explain(result: ClassificationResult) -> str:
    """Return a human-readable explanation suitable for audit log / UI."""
    if result.short_circuit == "whitelist":
        return f"白名单命中 → {result.level}"
    if result.short_circuit == "urgent_keyword":
        return f"紧急词命中 → {result.level}"
    parts = [f"{k}={v}" for k, v in result.dimensions.items()]
    return f"6维评分={result.score:.2f} → {result.level}\n  " + " | ".join(parts)
