"""PilotLearner · 学习闭环（评委 wow #3）.

监听 Domain Event Bus 的 ``task_delivered`` 事件，把 ``(intent, owner,
audience, output_primary, plan_outline)`` 写进 archival JSONL。

当某个新任务进来：
- 计算与历史任务的 token 相似度（rank-bm25 / Jaccard 简化）
- 若 ≥ 3 条相似（threshold ≥ 0.6）→ 自动生成 ``SKILL.md`` 写入 ``.larkmentor/skills/auto/``
- 第 4 次类似任务直接命中 SKILL，跳过部分规划

文件结构：
- ``data/learner/archival.jsonl``    历史任务向量化记录
- ``.larkmentor/skills/auto/<slug>/SKILL.md``    自动生成的 skill

设计要点：
1. 不依赖 mem0ai / qdrant / sqlite-fts5（避免 P0 baseline 那些慢依赖）
2. 纯 Python，2C2G 友好，10ms 级匹配
3. 通过 ``EventBus.subscribe(kind=EVT_TASK_DELIVERED)`` 自动启用
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..domain import (
    EventBus,
    Task,
    default_event_bus,
)
from ..domain.events import (
    EVT_TASK_DELIVERED,
    DomainEvent,
)

logger = logging.getLogger("pilot.application.learner")


# ── 数据结构 ────────────────────────────────────────────────────────────────


@dataclass
class TaskMemory:
    """归档单条任务."""

    task_id: str
    intent: str
    owner_open_id: str = ""
    title: str = ""
    output_primary: str = "doc"
    output_audience: str = ""
    plan_outline: List[str] = field(default_factory=list)
    artifacts_count: int = 0
    delivered_ts: int = 0
    tokens: List[str] = field(default_factory=list)
    skill_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id, "intent": self.intent,
            "owner_open_id": self.owner_open_id, "title": self.title,
            "output_primary": self.output_primary,
            "output_audience": self.output_audience,
            "plan_outline": self.plan_outline,
            "artifacts_count": self.artifacts_count,
            "delivered_ts": self.delivered_ts,
            "tokens": self.tokens,
            "skill_id": self.skill_id,
        }


@dataclass
class GeneratedSkill:
    skill_id: str
    title: str
    description: str
    intent_pattern: str
    plan_template: List[str]
    examples: List[str]
    md_path: str = ""
    created_ts: int = 0
    hit_count: int = 0


# ── tokenizer 简化 ──────────────────────────────────────────────────────────


_STOPWORDS = set("的 了 在 是 给 把 帮 我 你 他 它 我们 你们 他们 一下 一个".split())


def tokenize(text: str) -> List[str]:
    """中文 + 英文混合的简易 tokenizer.

    中文：字 bigram（每 2 字一组），英文：word lowercase。"""
    text = (text or "").strip()
    if not text:
        return []
    en = re.findall(r"[A-Za-z][A-Za-z0-9_-]+", text)
    en_tokens = [w.lower() for w in en if len(w) >= 2]
    cn = re.sub(r"[^\u4e00-\u9fff]", "", text)
    cn_bigrams = [cn[i:i + 2] for i in range(len(cn) - 1) if len(cn[i:i + 2]) == 2]
    out = en_tokens + cn_bigrams
    return [t for t in out if t not in _STOPWORDS]


def jaccard(a: List[str], b: List[str]) -> float:
    """Jaccard 相似度 (0-1)."""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


# ── 主体 ────────────────────────────────────────────────────────────────────


class PilotLearner:
    """学习闭环."""

    def __init__(
        self,
        *,
        archival_path: str = "data/learner/archival.jsonl",
        skills_root: str = ".larkmentor/skills/auto",
        similarity_threshold: float = 0.4,
        min_similar_tasks: int = 3,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.archival_path = Path(archival_path)
        self.skills_root = Path(skills_root)
        self.archival_path.parent.mkdir(parents=True, exist_ok=True)
        self.skills_root.mkdir(parents=True, exist_ok=True)
        self.similarity_threshold = similarity_threshold
        self.min_similar_tasks = min_similar_tasks
        self.bus = event_bus or default_event_bus()
        self._memories: List[TaskMemory] = self._load_archival()
        self._skills: List[GeneratedSkill] = self._load_skills()

    def attach_to_bus(self) -> None:
        """订阅 task_delivered 事件，自动学习."""
        self.bus.subscribe(self._on_event, kind=EVT_TASK_DELIVERED)

    # ── 事件回调 ──────────────────────────────────────────────────────────
    def _on_event(self, ev: DomainEvent) -> None:
        # event 不持有 Task 对象引用，需要通过 task_service 反查
        try:
            from .task_service import default_task_service
            task = default_task_service().get(ev.task_id)
            if task:
                self.learn_from_task(task)
        except Exception as e:
            logger.debug("learner cannot fetch task: %s", e)

    # ── 主入口 ────────────────────────────────────────────────────────────
    def learn_from_task(self, task: Task) -> Optional[GeneratedSkill]:
        """归档任务，并尝试生成 SKILL.

        返回 None 表示未生成；返回 GeneratedSkill 表示已生成新 skill。
        """
        mem = TaskMemory(
            task_id=task.task_id,
            intent=task.intent,
            owner_open_id=task.owner_lock.owner_open_id,
            title=task.title,
            output_primary=(task.context_pack.output_requirements.primary
                              if task.context_pack else "doc"),
            output_audience=(task.context_pack.output_requirements.audience
                              if task.context_pack else ""),
            plan_outline=[s.tool for s in (task.plan.steps if task.plan else [])],
            artifacts_count=len(task.artifacts),
            delivered_ts=int(time.time()),
            tokens=tokenize(task.intent + " " + task.title),
        )

        # 找相似
        similars = self.find_similar(mem.tokens, threshold=self.similarity_threshold)
        # 把当前任务也加到候选（避免 self-match 影响 count）
        if len(similars) >= self.min_similar_tasks - 1:
            # 已经有 N-1 条以前的相似 + 当前 = N → 触发生成
            skill = self._generate_skill(mem, similars)
            mem.skill_id = skill.skill_id
        # 写入 archival
        self._memories.append(mem)
        self._append_archival(mem)
        return self._skills[-1] if (mem.skill_id and self._skills) else None

    # ── 检索 ──────────────────────────────────────────────────────────────
    def find_similar(self, tokens: List[str], *, threshold: float = 0.4,
                      top_k: int = 5) -> List[Tuple[TaskMemory, float]]:
        scored = []
        for m in self._memories:
            s = jaccard(tokens, m.tokens)
            if s >= threshold:
                scored.append((m, s))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def hit_skill(self, intent: str) -> Optional[GeneratedSkill]:
        """新任务进来时检查是否命中已生成的 skill."""
        tk = tokenize(intent)
        if not tk:
            return None
        for sk in self._skills:
            ptk = tokenize(sk.intent_pattern)
            if jaccard(tk, ptk) >= self.similarity_threshold:
                sk.hit_count += 1
                return sk
        return None

    def list_skills(self) -> List[GeneratedSkill]:
        return list(self._skills)

    def stats(self) -> Dict[str, int]:
        return {
            "memories": len(self._memories),
            "skills": len(self._skills),
            "skill_hit_count": sum(s.hit_count for s in self._skills),
        }

    # ── 生成 SKILL ────────────────────────────────────────────────────────
    def _generate_skill(self, mem: TaskMemory,
                          similars: List[Tuple[TaskMemory, float]]) -> GeneratedSkill:
        # 提取共同 plan_outline（每步最常出现的 tool）
        all_plans = [m.plan_outline for m, _ in similars] + [mem.plan_outline]
        flat = [t for plan in all_plans for t in plan]
        common = [t for t, _ in Counter(flat).most_common(8)]

        slug = re.sub(r"[^a-z0-9]+", "-", mem.title.lower()) or f"skill-{uuid.uuid4().hex[:6]}"
        slug = slug.strip("-")[:32] or f"skill-{uuid.uuid4().hex[:6]}"

        skill = GeneratedSkill(
            skill_id=f"sk-{uuid.uuid4().hex[:8]}",
            title=mem.title or mem.intent[:30],
            description=f"基于 {len(similars) + 1} 次相似任务自动归纳",
            intent_pattern=mem.intent,
            plan_template=common,
            examples=[m.intent for m, _ in similars][:3],
            created_ts=int(time.time()),
        )
        # 落盘 SKILL.md
        skill_dir = self.skills_root / slug
        skill_dir.mkdir(parents=True, exist_ok=True)
        md_path = skill_dir / "SKILL.md"
        md = self._render_skill_md(skill, mem, similars)
        md_path.write_text(md, encoding="utf-8")
        skill.md_path = str(md_path)
        self._skills.append(skill)
        logger.info("learner generated SKILL %s at %s", skill.skill_id, md_path)
        return skill

    @staticmethod
    def _render_skill_md(skill: GeneratedSkill, latest: TaskMemory,
                           similars: List[Tuple[TaskMemory, float]]) -> str:
        examples_md = "\n".join(f"- _{m.intent[:140]}_" for m, _ in similars[:3])
        plan_md = "\n".join(f"{i+1}. {t}" for i, t in enumerate(skill.plan_template[:8]))
        return f"""# {skill.title}

> Auto-generated from {len(similars) + 1} similar tasks (PilotLearner)
> Skill ID: `{skill.skill_id}`
> Created: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(skill.created_ts))}

## Intent Pattern

{skill.intent_pattern}

## Plan Template

{plan_md or "（暂无）"}

## Examples

{examples_md or "（暂无）"}

## Trigger

When a new task matches this pattern (Jaccard ≥ 0.4 on intent tokens),
the planner will skip outline regeneration and reuse this template.

## How to disable

Delete this directory: `{skill.md_path or '<auto-generated>'}`
"""

    # ── 持久化 ────────────────────────────────────────────────────────────
    def _load_archival(self) -> List[TaskMemory]:
        if not self.archival_path.exists():
            return []
        out: List[TaskMemory] = []
        try:
            for line in self.archival_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    out.append(TaskMemory(**d))
                except Exception:
                    continue
        except Exception:
            pass
        return out

    def _append_archival(self, mem: TaskMemory) -> None:
        try:
            with self.archival_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(mem.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("archival append failed: %s", e)

    def _load_skills(self) -> List[GeneratedSkill]:
        out: List[GeneratedSkill] = []
        if not self.skills_root.exists():
            return out
        for p in self.skills_root.iterdir():
            md = p / "SKILL.md"
            if not md.exists():
                continue
            content = md.read_text(encoding="utf-8")
            m = re.search(r"Skill ID: `([^`]+)`", content)
            sid = m.group(1) if m else f"sk-{p.name[:8]}"
            title = content.splitlines()[0].lstrip("# ").strip()
            # 提取 intent pattern
            mp = re.search(r"## Intent Pattern\n\n(.*?)\n\n## ", content, re.DOTALL)
            ip = (mp.group(1).strip() if mp else "")
            out.append(GeneratedSkill(
                skill_id=sid, title=title, description="",
                intent_pattern=ip, plan_template=[], examples=[],
                md_path=str(md),
            ))
        return out


_default_learner: Optional[PilotLearner] = None


def default_pilot_learner() -> PilotLearner:
    global _default_learner
    if _default_learner is None:
        root = os.getenv("PILOT_LEARNER_ROOT", "data/learner")
        skills = os.getenv("PILOT_SKILLS_ROOT", ".larkmentor/skills/auto")
        _default_learner = PilotLearner(
            archival_path=str(Path(root) / "archival.jsonl"),
            skills_root=skills,
        )
    return _default_learner


__all__ = [
    "PilotLearner",
    "TaskMemory",
    "GeneratedSkill",
    "default_pilot_learner",
    "tokenize",
    "jaccard",
]
