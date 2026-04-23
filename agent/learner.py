"""Learning Loop · Hermes Agent 独门绝技

每 N 次交互后 pause 自省 → 检测重复模式（同类任务 ≥3 次）→ 自动生成 SKILL.md。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent.learner")


@dataclass
class TaskRecord:
    intent: str
    session_id: str
    kind: str  # normalized task kind
    fingerprint: str
    outcome_summary: str
    ts: float = field(default_factory=time.time)


def _fingerprint(intent: str) -> str:
    """Stable fingerprint of intent: lowercased, punctuation stripped, first 5 key keywords."""
    norm = re.sub(r'[\W\s]+', ' ', intent.lower())
    words = [w for w in norm.split() if len(w) > 2][:8]
    h = hashlib.md5(" ".join(sorted(words)).encode()).hexdigest()[:12]
    return h


class LearningLoop:
    """Detect repeated patterns → auto generate user-generated SKILL.md."""

    def __init__(self, *, pause_every: int = 5, threshold: int = 3) -> None:
        self.pause_every = pause_every
        self.threshold = threshold
        self.records: List[TaskRecord] = []
        self.home = Path.cwd() / ".larkmentor" / "skills" / "user-generated"
        self.home.mkdir(parents=True, exist_ok=True)
        self.trace_path = Path.cwd() / ".larkmentor" / "learner_trace.jsonl"
        self._load_trace()

    def _load_trace(self) -> None:
        if not self.trace_path.exists():
            return
        try:
            with self.trace_path.open() as f:
                for line in f:
                    data = json.loads(line.strip())
                    self.records.append(TaskRecord(**data))
        except Exception as e:
            logger.debug("learner trace load failed: %s", e)

    def record(self, *, intent: str, session_id: str, outcome_summary: str, kind: str = "") -> None:
        fp = _fingerprint(intent)
        rec = TaskRecord(
            intent=intent[:400], session_id=session_id,
            kind=kind or self._classify_kind(intent),
            fingerprint=fp,
            outcome_summary=outcome_summary[:400],
        )
        self.records.append(rec)
        try:
            with self.trace_path.open("a") as f:
                f.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")
        except Exception:
            pass

        # Trigger check every N records
        if len(self.records) % self.pause_every == 0:
            self._check_and_generate()

    def _classify_kind(self, intent: str) -> str:
        intent_lower = intent.lower()
        mapping = {
            "doc": ["文档", "写", "撰写", "draft", "document"],
            "report": ["周报", "汇报", "report", "summary"],
            "plan": ["方案", "规划", "plan"],
            "slides": ["ppt", "演示", "slides"],
            "canvas": ["画板", "架构图", "流程图"],
            "debate": ["方案比较", "debate", "选哪个"],
        }
        for k, kws in mapping.items():
            if any(kw in intent_lower for kw in kws):
                return k
        return "general"

    def _check_and_generate(self) -> None:
        """Find patterns that appear ≥ threshold times and haven't been skilled yet."""
        by_fp: Dict[str, List[TaskRecord]] = {}
        for r in self.records:
            by_fp.setdefault(r.fingerprint, []).append(r)

        for fp, records in by_fp.items():
            if len(records) >= self.threshold:
                # Check if skill already exists
                kind = records[0].kind
                slug = f"{kind}-{fp[:6]}"
                skill_dir = self.home / slug
                if skill_dir.exists():
                    continue
                try:
                    self._generate_skill(slug, records)
                    self._notify_user_wow(slug, str(skill_dir / "SKILL.md"))
                except Exception as e:
                    logger.warning("skill generation failed for %s: %s", slug, e)

    def _generate_skill(self, slug: str, records: List[TaskRecord]) -> None:
        skill_dir = self.home / slug
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"

        # Common keywords from intents
        all_text = " ".join(r.intent for r in records)
        kws = list(set(re.findall(r'[\u4e00-\u9fff]{2,6}', all_text)))[:15]

        kind = records[0].kind
        description = f"自动生成的 skill：处理 {kind} 类任务（从 {len(records)} 次相似请求中学习）"

        body = f"""---
name: {slug}
description: {description[:1536]}
auto_generated: true
generated_at: {time.strftime("%Y-%m-%d %H:%M:%S")}
trigger_count: {len(records)}
---

# Skill: {slug}

由 LearningLoop 在 {time.strftime("%Y-%m-%d")} 自动生成。

## 触发条件

最近用户反复发起了以下相似请求（{len(records)} 次）：

"""
        for r in records[:5]:
            body += f"- {r.intent[:160]}\n"

        body += f"""

## 推荐关键词

{", ".join(f"`{k}`" for k in kws)}

## 推荐的工作流

根据之前成功的输出总结：

"""
        for r in records[:3]:
            body += f"### 示例 {records.index(r) + 1}\n**请求：** {r.intent[:160]}\n**结果：** {r.outcome_summary[:200]}\n\n"

        body += """

## 模板

未来遇到这类任务时，可直接参考上述输出格式和关键词组合，不必重新思考。
"""
        skill_path.write_text(body, encoding="utf-8")
        logger.info("🎓 LearningLoop 自动生成 skill: %s (%d records)", skill_path, len(records))

    def _notify_user_wow(self, slug: str, skill_path: str) -> None:
        """Emit an event for the bot/dashboard to display wow card."""
        # Append to events log
        events_log = Path.cwd() / ".larkmentor" / "learner_events.jsonl"
        try:
            with events_log.open("a") as f:
                f.write(json.dumps({
                    "kind": "skill_generated",
                    "slug": slug,
                    "path": skill_path,
                    "ts": int(time.time()),
                }) + "\n")
        except Exception:
            pass

    def stats(self) -> Dict[str, Any]:
        by_kind: Dict[str, int] = {}
        by_fp: Dict[str, int] = {}
        for r in self.records:
            by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
            by_fp[r.fingerprint] = by_fp.get(r.fingerprint, 0) + 1
        return {
            "total_records": len(self.records),
            "by_kind": by_kind,
            "unique_fingerprints": len(by_fp),
            "skills_generated": len(list(self.home.glob("*/SKILL.md"))),
        }


_singleton: Optional[LearningLoop] = None


def default_learner() -> LearningLoop:
    global _singleton
    if _singleton is None:
        _singleton = LearningLoop()
    return _singleton
