"""Advanced FlowGuard features for finals-grade differentiation.

Modules:
    1. Meeting Linkage    – pre-meeting reminder + post-meeting brief
    2. Circuit Breaker    – emergency burst auto-exit (live in smart_shield)
    3. Decision Rollback  – let user undo "你刚刚把 X 判成 P3"
    4. Explainable AI     – per-decision audit log with 6-dim breakdown
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional

from utils.time_utils import now_ts, fmt_time

logger = logging.getLogger("flowguard.advanced")

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)
DECISION_LOG_FILE = os.path.join(DATA_DIR, "decision_log.json")


# ─── 1. Meeting Linkage ──────────────────────────────────────────

def build_pre_meeting_brief(meeting_title: str, related_tasks: List[str], related_docs: List[str]) -> str:
    """Compose a 5-line pre-meeting brief shown to the user 10 min before start."""
    lines = [f"**会前 10 分钟提醒** · {meeting_title}", ""]
    if related_tasks:
        lines.append("📋 相关任务：")
        for t in related_tasks[:3]:
            lines.append(f"  - {t}")
    if related_docs:
        lines.append("📄 相关文档：")
        for d in related_docs[:3]:
            lines.append(f"  - {d}")
    lines.append("")
    lines.append("💡 建议提前 5 分钟开启 `专注15分钟` 进入心流，会议结束自动恢复。")
    return "\n".join(lines)


def build_post_meeting_brief(meeting_title: str, captured_pending_count: int, pending_summary: str = "") -> str:
    """Compose a 'welcome back from meeting' brief."""
    return (
        f"**会议结束 · {meeting_title}**\n\n"
        f"会议期间为你拦截了 **{captured_pending_count}** 条消息。\n\n"
        f"{pending_summary if pending_summary else '所有消息已分级处理，详情请查看打断分析。'}\n\n"
        f"💡 输入 `今日报告` 查看完整看板。"
    )


# ─── 3. Decision Rollback ────────────────────────────────────────

@dataclass
class DecisionRecord:
    decision_id: str
    timestamp: int
    user_open_id: str
    sender_id: str
    sender_name: str
    message_preview: str
    classification_level: str
    classification_score: float
    dimensions: Dict[str, float] = field(default_factory=dict)
    action_taken: str = ""
    used_llm: bool = False
    rolled_back: bool = False
    rollback_to_level: str = ""
    rollback_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_decisions: Dict[str, DecisionRecord] = {}


def record_decision(rec: DecisionRecord):
    _decisions[rec.decision_id] = rec
    _save()


def rollback_decision(decision_id: str, new_level: str, reason: str = "user_corrected") -> Optional[DecisionRecord]:
    rec = _decisions.get(decision_id)
    if not rec:
        return None
    rec.rolled_back = True
    rec.rollback_to_level = new_level
    rec.rollback_reason = reason
    _save()

    # Feedback into sender profile
    try:
        from core.sender_profile import get_profile
        p = get_profile(rec.sender_id, rec.sender_name)
        old_was_low = rec.classification_level in ("P2", "P3")
        new_is_high = new_level in ("P0", "P1")
        if old_was_low and new_is_high:
            p.user_marked_important += 2
        elif (rec.classification_level in ("P0", "P1")) and new_level in ("P2", "P3"):
            p.user_marked_unimportant += 2
        from core.sender_profile import save
        save()
    except Exception as e:
        logger.debug("rollback feedback to profile failed: %s", e)
    return rec


def list_recent_decisions(user_open_id: str, limit: int = 10) -> List[DecisionRecord]:
    items = [r for r in _decisions.values() if r.user_open_id == user_open_id]
    items.sort(key=lambda r: r.timestamp, reverse=True)
    return items[:limit]


# ─── 4. Explainable AI ───────────────────────────────────────────

def explain_decision(rec: DecisionRecord) -> str:
    """Return a multi-line human-readable explanation of why this verdict."""
    if not rec.dimensions:
        return f"分级为 {rec.classification_level}（未记录详细维度）"
    lines = [f"**为什么判为 {rec.classification_level}（分数 {rec.classification_score:.2f}）：**"]
    dim_labels = {
        "identity": "身份权重", "relation": "关系强度", "content": "内容信号",
        "task_relation": "任务关联", "time": "时间敏感", "channel": "频道权重",
    }
    for k, v in rec.dimensions.items():
        label = dim_labels.get(k, k)
        bar = _bar(v)
        lines.append(f"  - {label}: {v:.2f} {bar}")
    if rec.used_llm:
        lines.append("\n（已经过 LLM 复审）")
    if rec.rolled_back:
        lines.append(f"\n⚠️ 此决策已被你回滚至 {rec.rollback_to_level}")
    lines.append(f"\n时间：{fmt_time(rec.timestamp)}\n发送者：{rec.sender_name}\n消息：{rec.message_preview[:80]}")
    return "\n".join(lines)


def _bar(v: float, width: int = 10) -> str:
    filled = int(round(v * width))
    return "[" + "■" * filled + "·" * (width - filled) + "]"


# ─── Persistence ─────────────────────────────────────────────────

def _save():
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        data = {k: r.to_dict() for k, r in _decisions.items()}
        with open(DECISION_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Save decision log failed: %s", e)


def load():
    if not os.path.exists(DECISION_LOG_FILE):
        return
    try:
        with open(DECISION_LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            for d in data:
                if isinstance(d, dict) and "decision_id" in d:
                    _decisions[d["decision_id"]] = DecisionRecord(**d)
        elif isinstance(data, dict):
            for k, d in data.items():
                if isinstance(d, dict):
                    _decisions[k] = DecisionRecord(**d)
        logger.info("Loaded %d decisions", len(_decisions))
    except Exception as e:
        logger.error("Load decision log failed: %s", e)
