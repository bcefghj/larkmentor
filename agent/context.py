"""Context Manager · 5 层压缩（对齐 Claude Code query.ts 的 5 层管线）

论文 arxiv:2604.14228 §4.3 + decodeclaude.com 的 compaction-deep-dive。

压缩层级（从便宜到贵）：

| 层 | 阈值 | 策略 | 成本 |
|---|------|------|------|
| L1 Budget Reduction | 总在跑 | 单个 tool result > N tokens 截断 | 零 |
| L2 Snip | >40% | 删老 tool result，保留 hot tail N 个 | 零 |
| L3 Microcompact | >60% | 老 tool result → 磁盘引用 data/ctx/{ts}.json | 零 |
| L4 Context Collapse | >78% | read-time projection，段落压缩 git-log 摘要 | 零 |
| L5 Auto-Compact | >92% | fork subagent 9-section 结构化重写 | 一次 LLM |

原则：lossless before lossy, local before global。
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("agent.context")


# ── Token counting ───────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    """Rough estimate: 1 token ≈ 4 chars (English) or 1.5 chars (Chinese)."""
    if not text:
        return 0
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other = len(text) - chinese
    return int(chinese / 1.5 + other / 4)


def _size_of(msg: Dict[str, Any]) -> int:
    return _estimate_tokens(json.dumps(msg, ensure_ascii=False))


@dataclass
class CompactionEvent:
    layer: str  # "budget" / "snip" / "microcompact" / "collapse" / "autocompact"
    before_tokens: int
    after_tokens: int
    messages_affected: int
    ts: float = field(default_factory=time.time)
    reason: str = ""

    def ratio(self) -> float:
        if self.before_tokens == 0:
            return 0.0
        return 1 - self.after_tokens / self.before_tokens


class ContextManager:
    """5-layer context compression, Claude Code style."""

    def __init__(
        self,
        *,
        max_tokens: int = 128_000,
        single_result_cap: int = 8_000,
        hot_tail_size: int = 10,
        artifacts_dir: Optional[Path] = None,
    ) -> None:
        self.max_tokens = max_tokens
        self.single_result_cap = single_result_cap
        self.hot_tail_size = hot_tail_size
        self.artifacts_dir = artifacts_dir or Path.home() / ".larkmentor" / "ctx"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.history: List[CompactionEvent] = []

    # ── entry point ───────────────────────────────────────

    def shape(
        self,
        messages: List[Dict[str, Any]],
        *,
        protected_tail: int = 3,
    ) -> Tuple[List[Dict[str, Any]], List[CompactionEvent]]:
        """Run all 5 layers sequentially. Returns shaped messages + event log."""
        events: List[CompactionEvent] = []
        total = self._total_tokens(messages)

        # L1: Budget Reduction (always on)
        messages, ev = self._budget_reduction(messages)
        if ev:
            events.append(ev)

        total = self._total_tokens(messages)
        budget_pct = total / self.max_tokens

        # L2: Snip (>40%)
        if budget_pct > 0.40:
            messages, ev = self._snip(messages, protected_tail)
            if ev:
                events.append(ev)
            total = self._total_tokens(messages)
            budget_pct = total / self.max_tokens

        # L3: Microcompact (>60%)
        if budget_pct > 0.60:
            messages, ev = self._microcompact(messages, protected_tail)
            if ev:
                events.append(ev)
            total = self._total_tokens(messages)
            budget_pct = total / self.max_tokens

        # L4: Context Collapse (>78%)
        if budget_pct > 0.78:
            messages, ev = self._context_collapse(messages, protected_tail)
            if ev:
                events.append(ev)
            total = self._total_tokens(messages)
            budget_pct = total / self.max_tokens

        # L5: Auto-Compact (>92%)
        if budget_pct > 0.92:
            messages, ev = self._auto_compact(messages, protected_tail)
            if ev:
                events.append(ev)

        self.history.extend(events)
        return messages, events

    # ── Layers ───────────────────────────────────────

    def _budget_reduction(self, messages: List[Dict]) -> Tuple[List[Dict], Optional[CompactionEvent]]:
        """L1: truncate single tool result > cap."""
        before = self._total_tokens(messages)
        affected = 0
        for msg in messages:
            if msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            if isinstance(content, str) and _estimate_tokens(content) > self.single_result_cap:
                char_cap = self.single_result_cap * 4
                msg["content"] = content[:char_cap] + f"\n\n[...truncated by L1 budget ({_estimate_tokens(content)} → {self.single_result_cap} tokens)]"
                affected += 1
        after = self._total_tokens(messages)
        if affected == 0:
            return messages, None
        return messages, CompactionEvent("budget", before, after, affected, reason="single tool result over cap")

    def _snip(self, messages: List[Dict], protected_tail: int) -> Tuple[List[Dict], Optional[CompactionEvent]]:
        """L2: delete old tool results, keep hot tail."""
        before = self._total_tokens(messages)
        system = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        if len(non_system) <= self.hot_tail_size + protected_tail:
            return messages, None
        tool_msgs_in_cold = [
            i for i, m in enumerate(non_system[:-self.hot_tail_size])
            if m.get("role") == "tool"
        ]
        if not tool_msgs_in_cold:
            return messages, None
        new_non_system = list(non_system)
        for idx in reversed(tool_msgs_in_cold):
            del new_non_system[idx]
        new_messages = system + new_non_system
        after = self._total_tokens(new_messages)
        return new_messages, CompactionEvent("snip", before, after, len(tool_msgs_in_cold), reason="budget>40%, drop cold tool results")

    def _microcompact(self, messages: List[Dict], protected_tail: int) -> Tuple[List[Dict], Optional[CompactionEvent]]:
        """L3: old tool results → disk reference."""
        before = self._total_tokens(messages)
        affected = 0
        for msg in messages[:-protected_tail] if len(messages) > protected_tail else []:
            if msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            if isinstance(content, str) and _estimate_tokens(content) > 500:
                ts = int(time.time() * 1000)
                artifact_path = self.artifacts_dir / f"{ts}_{affected}.json"
                artifact_path.write_text(
                    json.dumps({"role": "tool", "content": content}, ensure_ascii=False),
                    encoding="utf-8"
                )
                msg["content"] = f"[stored on disk, retrievable by path: {artifact_path}]\n\nHead: {content[:200]}..."
                msg["_ref"] = str(artifact_path)
                affected += 1
        after = self._total_tokens(messages)
        if affected == 0:
            return messages, None
        return messages, CompactionEvent("microcompact", before, after, affected, reason="budget>60%, offload to disk")

    def _context_collapse(self, messages: List[Dict], protected_tail: int) -> Tuple[List[Dict], Optional[CompactionEvent]]:
        """L4: collapse middle chunk into git-log style summary (read-time projection)."""
        before = self._total_tokens(messages)
        if len(messages) < protected_tail + 10:
            return messages, None
        system = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        head = non_system[:2]
        tail = non_system[-(self.hot_tail_size):]
        middle = non_system[2:-self.hot_tail_size] if len(non_system) > self.hot_tail_size + 2 else []
        if not middle:
            return messages, None
        summary_lines = []
        for m in middle:
            role = m.get("role", "?")
            content = m.get("content", "")
            if isinstance(content, str):
                summary_lines.append(f"- [{role}] {content[:80]}...")
            else:
                summary_lines.append(f"- [{role}] <structured>")
        collapsed = {
            "role": "system",
            "content": f"=== Context Collapse ({len(middle)} messages) ===\n" + "\n".join(summary_lines[:30])
        }
        new_messages = system + head + [collapsed] + tail
        after = self._total_tokens(new_messages)
        return new_messages, CompactionEvent("collapse", before, after, len(middle), reason="budget>78%, collapse middle to summary")

    def _auto_compact(self, messages: List[Dict], protected_tail: int) -> Tuple[List[Dict], Optional[CompactionEvent]]:
        """L5: fork subagent to write structured 9-section working-state summary.

        Without LLM available we fall back to a heuristic 9-section summary
        that keeps user intent + recent files + pending tasks.
        """
        before = self._total_tokens(messages)
        sections = {
            "user_intent": "",
            "key_decisions": [],
            "technical_concepts": [],
            "files_touched": [],
            "errors_encountered": [],
            "pending_tasks": [],
            "recent_5_files": [],
            "current_state": "",
            "next_step": "",
        }
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "") or ""
            if not isinstance(content, str):
                continue
            if role == "user" and not sections["user_intent"]:
                sections["user_intent"] = content[:300]
            if role == "tool" and "path" in content.lower():
                sections["files_touched"].append(content[:120])
            if "error" in content.lower() or "failed" in content.lower():
                sections["errors_encountered"].append(content[:120])
            if "todo" in content.lower() or "pending" in content.lower():
                sections["pending_tasks"].append(content[:120])
        sections["recent_5_files"] = sections["files_touched"][-5:]
        tail_msg = messages[-1]["content"] if messages else ""
        sections["current_state"] = tail_msg[:300] if isinstance(tail_msg, str) else "<structured>"

        summary = {
            "role": "system",
            "content": "=== AUTO-COMPACT (9-section structured working state) ===\n" +
                       json.dumps(sections, ensure_ascii=False, indent=2)
        }
        system = [m for m in messages if m.get("role") == "system"]
        tail = [m for m in messages if m.get("role") != "system"][-protected_tail:]
        new_messages = system + [summary] + tail
        after = self._total_tokens(new_messages)
        return new_messages, CompactionEvent("autocompact", before, after, len(messages) - len(new_messages), reason="budget>92%, 9-section rewrite")

    # ── Helpers ───────────────────────────────────────

    def _total_tokens(self, messages: List[Dict]) -> int:
        return sum(_size_of(m) for m in messages)

    def snapshot(self) -> Dict[str, Any]:
        """For /context command display."""
        return {
            "max_tokens": self.max_tokens,
            "recent_events": [
                {
                    "layer": e.layer,
                    "before": e.before_tokens,
                    "after": e.after_tokens,
                    "ratio": f"{e.ratio():.0%}",
                    "affected": e.messages_affected,
                    "reason": e.reason,
                    "ts": int(e.ts),
                }
                for e in self.history[-10:]
            ],
            "artifacts_dir": str(self.artifacts_dir),
        }


_singleton: Optional[ContextManager] = None


def default_context_manager() -> ContextManager:
    global _singleton
    if _singleton is None:
        max_tokens = int(os.getenv("LARKMENTOR_CTX_MAX_TOKENS", "128000"))
        _singleton = ContextManager(max_tokens=max_tokens)
    return _singleton
