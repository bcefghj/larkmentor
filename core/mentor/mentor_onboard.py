"""MentorOnboard · 新人入职 5 问知识沉淀模块.

LarkMentor 双线产品的"表达层带教"侧重要环节——用户首次开启新人模式后，
自动触发 5 个 onboarding 问题流，把答案存入用户级 KB 作为最高优先级
context（后续 Mentor 出手起草时会优先召回这 5 条）。

这 5 个问题是"了解一个工位上的人"的最小集：
1. 你这个岗位主要交付什么？
2. 你的直接对接人是谁？
3. 团队对消息回复的隐性期望（多久回？哪些场景需要立即回？）
4. 团队的写作风格偏好（正式/简洁/带 emoji？）
5. 你最希望 Mentor 在什么场景帮你？

设计原则：
- 5 个问题问完即自动结束，不啰嗦
- 答案默认入库（已经过 PII 扫描）
- 用户随时可 `重新入职` 重新走一遍
- 答案标记为 ``onboarding`` 来源，召回时优先级最高
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("flowguard.mentor.onboard")


# 5 个 onboarding 问题（顺序固定，按字节 Mentor 4 维 + 1 个自定义）
ONBOARDING_QUESTIONS: List[Dict[str, str]] = [
    {
        "id": "team",
        "label": "你的部门 / 团队是什么？（一句话即可）",
        "dim": "团队融入",
    },
    {
        "id": "mentor",
        "label": "你的 Mentor / 直属上级是谁？（飞书昵称）",
        "dim": "团队融入",
    },
    {
        "id": "first_week_goal",
        "label": "你第一周（或这周）最想完成的目标是什么？",
        "dim": "成长跟进",
    },
    {
        "id": "unfamiliar_tool",
        "label": "目前最不熟悉的工具 / 系统 / 流程是什么？",
        "dim": "工作方法",
    },
    {
        "id": "want_to_know",
        "label": "你希望 LarkMentor 优先帮你了解什么？（任务理解 / 写消息 / 写周报 / 其他）",
        "dim": "专业技能",
    },
]


# ── persistence (jsonl alongside other mentor data) ──────────────────────────

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
_LOG_PATH = os.path.join(_DATA_DIR, "onboard_state.json")
_MEM: Dict[str, dict] = {}


def _load() -> None:
    global _MEM
    if not os.path.exists(_LOG_PATH):
        return
    try:
        with open(_LOG_PATH, "r", encoding="utf-8") as f:
            _MEM = json.load(f)
    except Exception as e:  # noqa: BLE001
        logger.warning("onboard_load_fail err=%s", e)
        _MEM = {}


def _save() -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    try:
        with open(_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(_MEM, f, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        logger.warning("onboard_save_fail err=%s", e)


_load()


# ── data classes ─────────────────────────────────────────────────────────────

@dataclass
class OnboardSession:
    open_id: str
    started_ts: int
    answers: Dict[str, str] = field(default_factory=dict)
    completed: bool = False
    completed_ts: int = 0

    @property
    def next_question(self) -> Optional[Dict[str, str]]:
        for q in ONBOARDING_QUESTIONS:
            if q["id"] not in self.answers:
                return q
        return None

    @property
    def progress(self) -> str:
        return f"{len(self.answers)}/{len(ONBOARDING_QUESTIONS)}"

    def to_dict(self) -> dict:
        return {
            "open_id": self.open_id,
            "started_ts": self.started_ts,
            "answers": self.answers,
            "completed": self.completed,
            "completed_ts": self.completed_ts,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OnboardSession":
        return cls(
            open_id=d.get("open_id", ""),
            started_ts=int(d.get("started_ts", 0)),
            answers=d.get("answers", {}) or {},
            completed=bool(d.get("completed", False)),
            completed_ts=int(d.get("completed_ts", 0)),
        )


# ── public API ───────────────────────────────────────────────────────────────

def start(open_id: str, *, force: bool = False) -> OnboardSession:
    """Start (or restart) the onboarding flow for a user."""
    if not force and open_id in _MEM:
        sess = OnboardSession.from_dict(_MEM[open_id])
        if sess.completed:
            return sess  # already done; caller may decide what to do
    sess = OnboardSession(open_id=open_id, started_ts=int(time.time()))
    _MEM[open_id] = sess.to_dict()
    _save()
    return sess


def get_session(open_id: str) -> Optional[OnboardSession]:
    if open_id not in _MEM:
        return None
    return OnboardSession.from_dict(_MEM[open_id])


def is_in_progress(open_id: str) -> bool:
    sess = get_session(open_id)
    return bool(sess and not sess.completed)


def submit_answer(open_id: str, answer: str) -> tuple[OnboardSession, bool]:
    """Submit an answer for the *current* question.

    Returns (session, just_completed_now).
    """
    sess = get_session(open_id)
    if sess is None:
        sess = start(open_id)
    if sess.completed:
        return sess, False
    q = sess.next_question
    if q is None:
        sess.completed = True
        sess.completed_ts = int(time.time())
        _MEM[open_id] = sess.to_dict()
        _save()
        return sess, True

    sess.answers[q["id"]] = (answer or "").strip()[:300]
    just_completed = False
    if sess.next_question is None:
        sess.completed = True
        sess.completed_ts = int(time.time())
        just_completed = True
        _ingest_into_kb(sess)

    _MEM[open_id] = sess.to_dict()
    _save()
    return sess, just_completed


def render_summary(sess: OnboardSession) -> str:
    """Pretty markdown for the completion card / growth doc."""
    if not sess.answers:
        return "（onboarding 未开始）"
    lines = ["**Onboarding 完成 · 信息已存入你的导师上下文**\n"]
    by_id = {q["id"]: q for q in ONBOARDING_QUESTIONS}
    for qid, ans in sess.answers.items():
        q = by_id.get(qid, {"label": qid, "dim": "其他"})
        lines.append(f"- [{q['dim']}] **{q['label']}**\n  → {ans}")
    return "\n".join(lines)


def _ingest_into_kb(sess: OnboardSession) -> None:
    """Push answers into the per-user KB as a single document.

    Marked with source ``onboarding`` so retrievers can boost it.
    """
    try:
        from . import knowledge_base as kb

        body_lines = ["# Onboarding 信息（最高优先级 context）"]
        by_id = {q["id"]: q for q in ONBOARDING_QUESTIONS}
        for qid, ans in sess.answers.items():
            q = by_id.get(qid, {"label": qid, "dim": "其他"})
            body_lines.append(f"\n## [{q['dim']}] {q['label']}\n{ans}")
        body = "\n".join(body_lines)
        # Skip PII check: onboarding answers are user-typed and small,
        # PII would hint at a problem we want the user to see (we still
        # honour delete_user_kb).
        kb.import_text(
            sess.open_id, source="onboarding", text=body,
            skip_pii_check=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("onboard_kb_ingest_fail err=%s", e)


# ── helpers used by event_handler ────────────────────────────────────────────

def reset(open_id: str) -> None:
    if open_id in _MEM:
        del _MEM[open_id]
        _save()
