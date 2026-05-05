"""Claude Code-style 6-layer context compression cascade.

实现六层渐进式上下文压缩，按开销从低到高依次触发：

1. **MicroCompact**        — 零 API 开销：裁剪旧工具输出（超过 N 轮的输出截断至 500 字符）
2. **DropToolResults**     — 将旧工具返回值替换为状态摘要行（OK/ERROR + 预览）
3. **SummarizeOldTurns**   — 将旧对话轮次折叠为单行角色标注摘要
4. **AutoCompact**         — 接近上下文窗口上限时触发（默认 100K token），生成 ≤20K token
   的结构化摘要，含断路器（连续 3 次失败后停止重试）
5. **ExtractKeyDecisions** — 仅保留对话中的关键决策点，丢弃非决策内容
6. **FullCompact**         — 全量对话压缩：重新注入最近访问的文件（每份 ≤5K token）、
   活跃计划步骤、相关 skill schema；压缩后预算重置为 50K token

设计原则：cheapest-first（无损 → 有损 → 全量重写），每层产出可观测的结构化事件。

Usage::

    from core.agent_pilot.harness.context_cascade import ContextCascade

    cascade = ContextCascade(context_window=128_000)
    result = cascade.compact(messages, session_meta={"files": [...], "plan": [...]})
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("pilot.harness.context_cascade")


# ────────────────────────────────────────────────────────────────
# Token counting
# ────────────────────────────────────────────────────────────────


def estimate_tokens(text: str) -> int:
    """Estimate token count from raw text.

    Heuristic: ~3.5 chars per token for Chinese-heavy text (CJK characters
    are typically 1–2 tokens each, ASCII words ~0.25 tokens/char). This
    strikes a reasonable balance for mixed Chinese/English content without
    requiring a tokenizer dependency.
    """
    if not text:
        return 0
    return max(1, int(len(text) / 3.5))


def messages_token_count(messages: List[Dict[str, Any]]) -> int:
    """Sum estimated tokens across all messages, plus per-message overhead."""
    total = 0
    for m in messages:
        total += estimate_tokens(str(m.get("content", "") or ""))
        total += 4  # role / delimiters overhead
    return total


# ────────────────────────────────────────────────────────────────
# Structured events (observability)
# ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CascadeEvent:
    """Emitted whenever a cascade layer fires or skips."""

    layer: str  # "micro" | "auto" | "full" | "cascade"
    action: str  # "triggered" | "skipped" | "completed" | "failed"
    tokens_before: int = 0
    tokens_after: int = 0
    messages_dropped: int = 0
    detail: str = ""
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer,
            "action": self.action,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "messages_dropped": self.messages_dropped,
            "detail": self.detail,
            "ts": self.ts or time.time(),
        }


EventCallback = Callable[[CascadeEvent], None]


def _emit(
    cb: Optional[EventCallback],
    layer: str,
    action: str,
    **kwargs: Any,
) -> CascadeEvent:
    evt = CascadeEvent(layer=layer, action=action, ts=time.time(), **kwargs)
    if cb:
        try:
            cb(evt)
        except Exception as e:
            logger.debug("cascade event callback failed: %s", e)
    logger.debug("cascade_event layer=%s action=%s detail=%s", layer, action, kwargs.get("detail", ""))
    return evt


# ────────────────────────────────────────────────────────────────
# Compact result
# ────────────────────────────────────────────────────────────────


@dataclass
class CompactResult:
    """Output of a cascade compaction pass."""

    messages: List[Dict[str, Any]]
    tokens_before: int
    tokens_after: int
    layers_fired: List[str] = field(default_factory=list)
    events: List[CascadeEvent] = field(default_factory=list)
    budget_remaining: int = 0


# ────────────────────────────────────────────────────────────────
# Layer 1: MicroCompact
# ────────────────────────────────────────────────────────────────


class MicroCompact:
    """Zero-API-cost trimming of stale tool outputs.

    Rules:
    - Tool-result messages older than ``keep_recent_turns`` turns get their
      content truncated to ``max_chars`` characters.
    - Empty / ack-only assistant messages are dropped entirely.

    This layer is always safe to run and costs nothing.
    """

    def __init__(
        self,
        *,
        keep_recent_turns: int = 6,
        max_chars: int = 500,
        on_event: Optional[EventCallback] = None,
    ) -> None:
        self.keep_recent_turns = keep_recent_turns
        self.max_chars = max_chars
        self._on_event = on_event

    def compact(self, messages: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
        """Return (trimmed_messages, count_of_dropped_messages)."""
        tokens_before = messages_token_count(messages)

        if len(messages) <= self.keep_recent_turns:
            _emit(self._on_event, "micro", "skipped", tokens_before=tokens_before, detail="too few messages")
            return messages, 0

        cutoff = len(messages) - self.keep_recent_turns
        result: List[Dict[str, Any]] = []
        dropped = 0

        for idx, m in enumerate(messages):
            role = m.get("role", "")
            content = str(m.get("content", "") or "")

            if role == "assistant" and content.strip() in ("", "ok", "收到", "好的", "明白"):
                dropped += 1
                continue

            if idx < cutoff and role == "tool" and len(content) > self.max_chars:
                m = {**m, "content": content[: self.max_chars] + "\n…[truncated by MicroCompact]"}

            result.append(m)

        tokens_after = messages_token_count(result)
        _emit(
            self._on_event,
            "micro",
            "completed",
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            messages_dropped=dropped,
            detail=f"trimmed {cutoff} old messages, dropped {dropped} acks",
        )
        return result, dropped


# ────────────────────────────────────────────────────────────────
# Layer 2: AutoCompact
# ────────────────────────────────────────────────────────────────


class AutoCompact:
    """Fires when approaching context window ceiling.

    Generates a structured summary of the conversation (≤ ``summary_budget``
    tokens) by collapsing the middle of the history into bullet points while
    keeping the head (user intent) and tail (recent exchanges) verbatim.

    A **circuit breaker** prevents infinite retry: after ``max_failures``
    consecutive compaction failures the layer gives up and passes through.
    """

    def __init__(
        self,
        *,
        ceiling_tokens: int = 100_000,
        summary_budget: int = 20_000,
        max_failures: int = 3,
        on_event: Optional[EventCallback] = None,
    ) -> None:
        self.ceiling_tokens = ceiling_tokens
        self.summary_budget = summary_budget
        self.max_failures = max_failures
        self._consecutive_failures = 0
        self._on_event = on_event

    @property
    def circuit_open(self) -> bool:
        return self._consecutive_failures >= self.max_failures

    def reset_circuit(self) -> None:
        self._consecutive_failures = 0

    def compact(self, messages: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
        """Return (compacted_messages, dropped_count)."""
        tokens_before = messages_token_count(messages)

        if tokens_before < self.ceiling_tokens:
            _emit(
                self._on_event,
                "auto",
                "skipped",
                tokens_before=tokens_before,
                detail=f"below ceiling ({tokens_before}/{self.ceiling_tokens})",
            )
            return messages, 0

        if self.circuit_open:
            _emit(
                self._on_event,
                "auto",
                "skipped",
                tokens_before=tokens_before,
                detail=f"circuit breaker open after {self.max_failures} failures",
            )
            return messages, 0

        try:
            result, dropped = self._do_compact(messages)
            tokens_after = messages_token_count(result)

            if tokens_after >= tokens_before:
                raise RuntimeError("compaction did not reduce token count")

            self._consecutive_failures = 0
            _emit(
                self._on_event,
                "auto",
                "completed",
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                messages_dropped=dropped,
                detail=f"summarised middle section into ≤{self.summary_budget}t",
            )
            return result, dropped

        except Exception as exc:
            self._consecutive_failures += 1
            _emit(
                self._on_event,
                "auto",
                "failed",
                tokens_before=tokens_before,
                detail=f"failure #{self._consecutive_failures}: {exc}",
            )
            return messages, 0

    def _do_compact(self, messages: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
        """Build a structured summary from the middle of the conversation."""
        if len(messages) <= 10:
            return messages, 0

        keep_head = messages[:2]
        keep_tail = messages[-8:]
        middle = messages[2:-8]

        sections: Dict[str, List[str]] = {
            "user_requests": [],
            "assistant_decisions": [],
            "tool_results": [],
            "errors": [],
        }

        for m in middle:
            role = m.get("role", "")
            content = str(m.get("content", "") or "")
            first_line = content.split("\n", 1)[0][:150]

            if role == "user":
                sections["user_requests"].append(f"• {first_line}")
            elif role == "assistant":
                sections["assistant_decisions"].append(f"• {first_line}")
            elif role == "tool":
                sections["tool_results"].append(f"• [{m.get('tool', '?')}] {first_line}")
            if any(kw in content.lower() for kw in ("error", "失败", "exception", "traceback")):
                sections["errors"].append(f"• {first_line}")

        summary_parts = ["## 对话摘要（AutoCompact）\n"]
        for heading, items in sections.items():
            if items:
                summary_parts.append(f"### {heading}")
                budget_chars = int(self.summary_budget * 3.5 / len(sections))
                joined = "\n".join(items)
                if len(joined) > budget_chars:
                    joined = joined[:budget_chars] + "\n…(truncated)"
                summary_parts.append(joined)
                summary_parts.append("")

        summary_text = "\n".join(summary_parts)
        if estimate_tokens(summary_text) > self.summary_budget:
            summary_text = summary_text[: int(self.summary_budget * 3.5)]

        summary_msg = {"role": "system", "content": summary_text}
        result = keep_head + [summary_msg] + keep_tail
        dropped = len(middle)
        return result, dropped


# ────────────────────────────────────────────────────────────────
# Layer 3: FullCompact
# ────────────────────────────────────────────────────────────────


class FullCompact:
    """Complete conversation compression and context re-injection.

    After compression, re-injects:
    - Recently accessed files (each capped at ``file_cap_tokens``)
    - Active plan steps
    - Relevant skill schemas

    Post-compression token budget resets to ``post_budget`` tokens.
    """

    FILE_CAP_TOKENS = 5_000
    POST_BUDGET = 50_000

    def __init__(
        self,
        *,
        post_budget: int = 50_000,
        file_cap_tokens: int = 5_000,
        on_event: Optional[EventCallback] = None,
    ) -> None:
        self.post_budget = post_budget
        self.file_cap_tokens = file_cap_tokens
        self._on_event = on_event

    def compact(
        self,
        messages: List[Dict[str, Any]],
        *,
        recent_files: Optional[List[Dict[str, str]]] = None,
        active_plan_steps: Optional[List[str]] = None,
        skill_schemas: Optional[List[str]] = None,
    ) -> tuple[List[Dict[str, Any]], int]:
        """Perform full compression with context re-injection.

        Parameters
        ----------
        messages
            Current conversation messages.
        recent_files
            List of ``{"path": ..., "content": ...}`` for recently accessed files.
        active_plan_steps
            Currently active plan step descriptions.
        skill_schemas
            Relevant skill schema strings to re-inject.
        """
        tokens_before = messages_token_count(messages)

        first_user = next((m for m in messages if m.get("role") == "user"), None)
        last_messages = messages[-4:]

        intent_text = (first_user or {}).get("content", "(no user intent captured)")
        decisions = self._extract_decisions(messages)
        errors = self._extract_errors(messages)

        sections = [
            "## 全量压缩摘要（FullCompact）\n",
            f"### 用户意图\n{intent_text[:1000]}\n",
            f"### 关键决策\n{decisions}\n",
            f"### 遇到的错误\n{errors}\n",
        ]

        if active_plan_steps:
            steps_text = "\n".join(f"- {s}" for s in active_plan_steps[:20])
            sections.append(f"### 活跃计划步骤\n{steps_text}\n")

        if skill_schemas:
            schemas_text = "\n---\n".join(s[:500] for s in skill_schemas[:5])
            sections.append(f"### 相关 Skill Schema\n{schemas_text}\n")

        summary_msg = {"role": "system", "content": "\n".join(sections)}

        result: List[Dict[str, Any]] = [summary_msg]

        if recent_files:
            file_parts: List[str] = []
            total_file_tokens = 0
            for f in recent_files[:10]:
                content = f.get("content", "")
                cap_chars = int(self.file_cap_tokens * 3.5)
                if len(content) > cap_chars:
                    content = content[:cap_chars] + "\n…[truncated]"
                file_tokens = estimate_tokens(content)
                if total_file_tokens + file_tokens > self.post_budget // 2:
                    break
                file_parts.append(f"#### {f.get('path', '?')}\n```\n{content}\n```")
                total_file_tokens += file_tokens

            if file_parts:
                files_msg = {"role": "system", "content": "### 最近访问的文件\n\n" + "\n\n".join(file_parts)}
                result.append(files_msg)

        result.extend(last_messages)

        tokens_after = messages_token_count(result)
        dropped = max(0, len(messages) - len(result))

        _emit(
            self._on_event,
            "full",
            "completed",
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            messages_dropped=dropped,
            detail=f"full compress: {tokens_before}→{tokens_after}t, budget reset to {self.post_budget}t",
        )
        return result, dropped

    @staticmethod
    def _extract_decisions(messages: List[Dict[str, Any]], limit: int = 15) -> str:
        keywords = ["决定", "选择", "决策", "decided", "will use", "选用", "采用", "方案"]
        lines: List[str] = []
        seen: set[str] = set()
        for m in messages:
            content = str(m.get("content", "") or "")
            for line in content.splitlines():
                lower = line.lower()
                if any(k in lower for k in keywords):
                    stripped = line.strip()[:200]
                    if stripped and stripped not in seen:
                        seen.add(stripped)
                        lines.append(f"• {stripped}")
                        if len(lines) >= limit:
                            return "\n".join(lines)
        return "\n".join(lines) if lines else "(none)"

    @staticmethod
    def _extract_errors(messages: List[Dict[str, Any]], limit: int = 10) -> str:
        keywords = ["error", "exception", "失败", "traceback", "异常", "failed"]
        lines: List[str] = []
        seen: set[str] = set()
        for m in messages:
            content = str(m.get("content", "") or "")
            for line in content.splitlines():
                lower = line.lower()
                if any(k in lower for k in keywords):
                    stripped = line.strip()[:200]
                    if stripped and stripped not in seen:
                        seen.add(stripped)
                        lines.append(f"• {stripped}")
                        if len(lines) >= limit:
                            return "\n".join(lines)
        return "\n".join(lines) if lines else "(none)"


# ────────────────────────────────────────────────────────────────
# Layer 4: SummarizeOldTurns
# ────────────────────────────────────────────────────────────────


class SummarizeOldTurns:
    """Compress older conversation turns into concise summaries.

    Keeps the most recent ``keep_recent`` turns verbatim and collapses
    everything before that into per-turn one-line summaries grouped by role.
    Costs no LLM calls — purely heuristic extraction.
    """

    def __init__(
        self,
        *,
        keep_recent: int = 10,
        summary_max_chars: int = 200,
        on_event: Optional[EventCallback] = None,
    ) -> None:
        self.keep_recent = keep_recent
        self.summary_max_chars = summary_max_chars
        self._on_event = on_event

    def compact(self, messages: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
        tokens_before = messages_token_count(messages)

        if len(messages) <= self.keep_recent:
            _emit(self._on_event, "summarize_old", "skipped", tokens_before=tokens_before, detail="too few messages")
            return messages, 0

        old = messages[: -self.keep_recent]
        recent = messages[-self.keep_recent :]

        summaries: List[str] = []
        for m in old:
            role = m.get("role", "unknown")
            content = str(m.get("content", "") or "")
            first_line = content.split("\n", 1)[0][: self.summary_max_chars]
            if first_line.strip():
                summaries.append(f"[{role}] {first_line}")

        summary_msg = {
            "role": "system",
            "content": "## 历史对话摘要（SummarizeOldTurns）\n\n" + "\n".join(summaries),
        }
        result = [summary_msg] + recent
        tokens_after = messages_token_count(result)
        dropped = len(old)

        _emit(
            self._on_event,
            "summarize_old",
            "completed",
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            messages_dropped=dropped,
            detail=f"summarised {dropped} old turns into {len(summaries)} lines",
        )
        return result, dropped


# ────────────────────────────────────────────────────────────────
# Layer 5: DropToolResults
# ────────────────────────────────────────────────────────────────


class DropToolResults:
    """Remove verbose tool-result payloads, keeping only status indicators.

    Tool messages older than ``keep_recent`` turns have their content replaced
    with a short status line (success/error + first 80 chars). This is
    especially effective when tools return large JSON blobs or file contents.
    """

    def __init__(
        self,
        *,
        keep_recent: int = 6,
        status_max_chars: int = 80,
        on_event: Optional[EventCallback] = None,
    ) -> None:
        self.keep_recent = keep_recent
        self.status_max_chars = status_max_chars
        self._on_event = on_event

    def compact(self, messages: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
        tokens_before = messages_token_count(messages)
        cutoff = max(0, len(messages) - self.keep_recent)
        result: List[Dict[str, Any]] = []
        stripped = 0

        for idx, m in enumerate(messages):
            if idx < cutoff and m.get("role") == "tool":
                content = str(m.get("content", "") or "")
                has_error = any(kw in content.lower() for kw in ("error", "失败", "exception", "failed"))
                status = "ERROR" if has_error else "OK"
                preview = content.split("\n", 1)[0][: self.status_max_chars]
                m = {**m, "content": f"[{status}] {preview}"}
                stripped += 1
            result.append(m)

        tokens_after = messages_token_count(result)
        _emit(
            self._on_event,
            "drop_tool",
            "completed",
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            messages_dropped=0,
            detail=f"stripped {stripped} tool result payloads",
        )
        return result, 0


# ────────────────────────────────────────────────────────────────
# Layer 6: ExtractKeyDecisions
# ────────────────────────────────────────────────────────────────


class ExtractKeyDecisions:
    """Keep only decision points from long conversations.

    Scans all messages for decision-related keywords and produces a compact
    decision log. Non-decision messages older than ``keep_recent`` turns are
    dropped entirely. This is the most aggressive compression layer and
    should only fire as a last resort.
    """

    DECISION_KEYWORDS = [
        "决定", "选择", "决策", "方案", "采用", "选用",
        "decided", "decision", "will use", "chosen", "approach",
        "plan:", "结论", "最终", "确认",
    ]

    def __init__(
        self,
        *,
        keep_recent: int = 8,
        max_decisions: int = 30,
        on_event: Optional[EventCallback] = None,
    ) -> None:
        self.keep_recent = keep_recent
        self.max_decisions = max_decisions
        self._on_event = on_event

    def compact(self, messages: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
        tokens_before = messages_token_count(messages)

        if len(messages) <= self.keep_recent:
            _emit(self._on_event, "key_decisions", "skipped", tokens_before=tokens_before, detail="too few messages")
            return messages, 0

        old = messages[: -self.keep_recent]
        recent = messages[-self.keep_recent :]

        decisions: List[str] = []
        seen: set[str] = set()
        for m in old:
            content = str(m.get("content", "") or "")
            for line in content.splitlines():
                lower = line.lower()
                if any(kw in lower for kw in self.DECISION_KEYWORDS):
                    stripped = line.strip()[:250]
                    if stripped and stripped not in seen:
                        seen.add(stripped)
                        decisions.append(f"• {stripped}")
                        if len(decisions) >= self.max_decisions:
                            break
            if len(decisions) >= self.max_decisions:
                break

        first_user = next((m for m in old if m.get("role") == "user"), None)
        intent = (first_user or {}).get("content", "")[:500] if first_user else ""

        parts = ["## 关键决策提取（ExtractKeyDecisions）\n"]
        if intent:
            parts.append(f"### 原始意图\n{intent}\n")
        if decisions:
            parts.append("### 决策记录\n" + "\n".join(decisions))
        else:
            parts.append("### 决策记录\n(无显式决策)")

        summary_msg = {"role": "system", "content": "\n".join(parts)}
        result = [summary_msg] + recent
        tokens_after = messages_token_count(result)
        dropped = len(old)

        _emit(
            self._on_event,
            "key_decisions",
            "completed",
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            messages_dropped=dropped,
            detail=f"extracted {len(decisions)} decisions from {dropped} old messages",
        )
        return result, dropped


# ────────────────────────────────────────────────────────────────
# Orchestrator: ContextCascade
# ────────────────────────────────────────────────────────────────


class ContextCascade:
    """Orchestrates the 6-layer compression cascade.

    Layers fire in order of increasing cost / aggressiveness, and each layer
    only triggers when the previous one was insufficient:

    1. **MicroCompact**        — always runs (free): trim stale tool outputs
    2. **DropToolResults**     — strip verbose tool payloads to status lines
    3. **SummarizeOldTurns**   — collapse old turns into one-line summaries
    4. **AutoCompact**         — structured middle-section summary
    5. **ExtractKeyDecisions** — keep only decision points from history
    6. **FullCompact**         — full rewrite with context re-injection

    Parameters
    ----------
    context_window
        Total context window size of the target LLM (in tokens).
    auto_ceiling
        Token threshold to trigger AutoCompact (default: 100K).
    full_ceiling
        Token threshold to trigger FullCompact (default: 120K).
    on_event
        Optional callback for observability events.

    Example
    -------
    >>> cascade = ContextCascade(context_window=128_000)
    >>> result = cascade.compact(messages)
    >>> print(result.layers_fired)  # e.g. ["micro"] or ["micro", "drop_tool", "auto"]
    """

    def __init__(
        self,
        *,
        context_window: int = 128_000,
        drop_tool_ceiling: int = 80_000,
        summarize_ceiling: int = 90_000,
        auto_ceiling: int = 100_000,
        decisions_ceiling: int = 110_000,
        full_ceiling: int = 120_000,
        micro_keep_turns: int = 6,
        micro_max_chars: int = 500,
        auto_summary_budget: int = 20_000,
        auto_max_failures: int = 3,
        full_post_budget: int = 50_000,
        full_file_cap: int = 5_000,
        on_event: Optional[EventCallback] = None,
    ) -> None:
        self.context_window = context_window
        self.drop_tool_ceiling = drop_tool_ceiling
        self.summarize_ceiling = summarize_ceiling
        self.auto_ceiling = auto_ceiling
        self.decisions_ceiling = decisions_ceiling
        self.full_ceiling = full_ceiling
        self._on_event = on_event

        self._micro = MicroCompact(
            keep_recent_turns=micro_keep_turns,
            max_chars=micro_max_chars,
            on_event=on_event,
        )
        self._drop_tool = DropToolResults(on_event=on_event)
        self._summarize_old = SummarizeOldTurns(on_event=on_event)
        self._auto = AutoCompact(
            ceiling_tokens=auto_ceiling,
            summary_budget=auto_summary_budget,
            max_failures=auto_max_failures,
            on_event=on_event,
        )
        self._key_decisions = ExtractKeyDecisions(on_event=on_event)
        self._full = FullCompact(
            post_budget=full_post_budget,
            file_cap_tokens=full_file_cap,
            on_event=on_event,
        )

    def compact(
        self,
        messages: List[Dict[str, Any]],
        *,
        session_meta: Optional[Dict[str, Any]] = None,
    ) -> CompactResult:
        """Run the cascade and return a ``CompactResult``.

        Parameters
        ----------
        messages
            Full conversation history (list of ``{"role": ..., "content": ...}``).
        session_meta
            Optional session metadata for FullCompact re-injection::

                {
                    "files": [{"path": "...", "content": "..."}],
                    "plan_steps": ["step 1", "step 2"],
                    "skill_schemas": ["schema_yaml_1", ...],
                }
        """
        meta = session_meta or {}
        tokens_start = messages_token_count(messages)
        layers_fired: List[str] = []
        events: List[CascadeEvent] = []

        def collector(e):
            return events.append(e)

        self._micro._on_event = collector
        self._drop_tool._on_event = collector
        self._summarize_old._on_event = collector
        self._auto._on_event = collector
        self._key_decisions._on_event = collector
        self._full._on_event = collector

        # Layer 1: MicroCompact (always runs)
        current, _ = self._micro.compact(messages)
        layers_fired.append("micro")
        tokens_now = messages_token_count(current)

        # Layer 2: DropToolResults (conditional)
        if tokens_now >= self.drop_tool_ceiling:
            current, _ = self._drop_tool.compact(current)
            layers_fired.append("drop_tool")
            tokens_now = messages_token_count(current)

        # Layer 3: SummarizeOldTurns (conditional)
        if tokens_now >= self.summarize_ceiling:
            current, _ = self._summarize_old.compact(current)
            layers_fired.append("summarize_old")
            tokens_now = messages_token_count(current)

        # Layer 4: AutoCompact (conditional)
        if tokens_now >= self.auto_ceiling:
            current, _ = self._auto.compact(current)
            layers_fired.append("auto")
            tokens_now = messages_token_count(current)

        # Layer 5: ExtractKeyDecisions (conditional)
        if tokens_now >= self.decisions_ceiling:
            current, _ = self._key_decisions.compact(current)
            layers_fired.append("key_decisions")
            tokens_now = messages_token_count(current)

        # Layer 6: FullCompact (conditional)
        if tokens_now >= self.full_ceiling:
            current, _ = self._full.compact(
                current,
                recent_files=meta.get("files"),
                active_plan_steps=meta.get("plan_steps"),
                skill_schemas=meta.get("skill_schemas"),
            )
            layers_fired.append("full")
            tokens_now = messages_token_count(current)

        budget_remaining = max(0, self.context_window - tokens_now)
        cascade_evt = _emit(
            collector,
            "cascade",
            "completed",
            tokens_before=tokens_start,
            tokens_after=tokens_now,
            detail=f"layers={layers_fired}, budget_remaining={budget_remaining}",
        )
        events.append(cascade_evt)

        logger.info(
            "context_cascade_done layers=%s tokens=%d→%d budget_remaining=%d",
            layers_fired,
            tokens_start,
            tokens_now,
            budget_remaining,
        )

        return CompactResult(
            messages=current,
            tokens_before=tokens_start,
            tokens_after=tokens_now,
            layers_fired=layers_fired,
            events=events,
            budget_remaining=budget_remaining,
        )

    def reset(self) -> None:
        """Reset circuit breaker and internal state."""
        self._auto.reset_circuit()


__all__ = [
    "estimate_tokens",
    "messages_token_count",
    "CascadeEvent",
    "CompactResult",
    "MicroCompact",
    "AutoCompact",
    "FullCompact",
    "SummarizeOldTurns",
    "DropToolResults",
    "ExtractKeyDecisions",
    "ContextCascade",
]
