"""Claude Code-style 4-layer context compression.

Token budget (tiktoken-cl100k-base approximation: chars/4):
* <40%   no-op
* >=40%  L1 HISTORY_SNIP     lossless removal of "noise" messages
* >=60%  L2 MICROCOMPACT     replace old tool results with disk references
* >=78%  L3 CONTEXT_COLLAPSE git-log style paragraph compression
* >=92%  L4 AUTOCOMPACT      9-section structured rewrite (lossy but preserved)

Principle: lossless before lossy, local before global.

The ContextManager is a pure utility: it takes a list of message dicts
(role, content) and returns a possibly-shorter list. Compaction decisions
fire the PreCompact hook so observers can snapshot transcripts first.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("pilot.harness.context")


# Approximate token counter (tiktoken-compatible enough for budgets).
def approx_tokens(text: str) -> int:
    if not text:
        return 0
    # 0.5 token/char for CJK, 0.25 for latin. Rough weighted average.
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    cjk_chars = len(text) - ascii_chars
    return int(ascii_chars / 4 + cjk_chars / 2) + 1


def messages_tokens(messages: List[Dict[str, Any]]) -> int:
    total = 0
    for m in messages:
        total += approx_tokens(str(m.get("content", "")))
        total += 4  # role / separators
    return total


@dataclass
class ContextSnapshot:
    messages: List[Dict[str, Any]]
    token_count: int
    total_budget: int
    compacted_at: int = 0
    layer: str = ""  # "", "L1", "L2", "L3", "L4"
    dropped: int = 0
    notes: str = ""


class ContextManager:
    """Maintains a rolling message window with 4-layer compaction."""

    def __init__(
        self,
        *,
        total_budget: int = 160_000,  # 160k tokens, aligned with modern LLMs
        output_headroom: int = 16_000,
        on_pre_compact: Optional[Callable[[str, List[Dict[str, Any]]], None]] = None,
        artifact_dir: Optional[str] = None,
    ) -> None:
        self.total_budget = total_budget
        self.output_headroom = output_headroom
        self.usable_budget = max(1024, total_budget - output_headroom)
        self._on_pre_compact = on_pre_compact
        self._artifact_dir = artifact_dir or os.path.expanduser("~/.larkmentor/artifacts")
        os.makedirs(self._artifact_dir, exist_ok=True)

    # ── Layer dispatcher ──

    def maybe_compact(self, messages: List[Dict[str, Any]]) -> ContextSnapshot:
        tokens = messages_tokens(messages)
        ratio = tokens / max(self.usable_budget, 1)
        layer = ""
        dropped = 0

        if ratio < 0.40:
            return ContextSnapshot(
                messages=messages, token_count=tokens,
                total_budget=self.total_budget, layer="", dropped=0,
                notes="no compaction; below 40% threshold",
            )

        if self._on_pre_compact:
            try:
                self._on_pre_compact("pre_compact_start", messages)
            except Exception:
                pass

        if ratio < 0.60:
            new_msgs, dropped = self._layer1_snip(messages)
            layer = "L1"
        elif ratio < 0.78:
            new_msgs, dropped = self._layer2_microcompact(messages)
            layer = "L2"
        elif ratio < 0.92:
            new_msgs, dropped = self._layer3_collapse(messages)
            layer = "L3"
        else:
            new_msgs, dropped = self._layer4_autocompact(messages)
            layer = "L4"

        new_tokens = messages_tokens(new_msgs)
        snapshot = ContextSnapshot(
            messages=new_msgs, token_count=new_tokens,
            total_budget=self.total_budget, compacted_at=int(time.time()),
            layer=layer, dropped=dropped,
            notes=f"compacted from {tokens} → {new_tokens} tokens via {layer}",
        )
        if self._on_pre_compact:
            try:
                self._on_pre_compact("post_compact_done", new_msgs)
            except Exception:
                pass
        logger.info("context compacted via %s: %d -> %d tokens, dropped=%d",
                    layer, tokens, new_tokens, dropped)
        return snapshot

    # ── L1: lossless HISTORY_SNIP ──

    def _layer1_snip(self, messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
        """Remove noise: ack messages, duplicate tool results, system chatter."""
        out: List[Dict[str, Any]] = []
        dropped = 0
        seen_tool_keys = set()

        for m in messages:
            content = str(m.get("content", "") or "")
            role = m.get("role", "")
            # Drop empty assistant acks.
            if role == "assistant" and content.strip() in ("", "ok", "收到", "好的"):
                dropped += 1
                continue
            # De-duplicate consecutive identical tool results.
            if role == "tool":
                key = (m.get("tool"), content[:80])
                if key in seen_tool_keys:
                    dropped += 1
                    continue
                seen_tool_keys.add(key)
            out.append(m)
        return out, dropped

    # ── L2: microcompact (replace old tool outputs with disk refs) ──

    def _layer2_microcompact(self, messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
        """Keep the last 3 tool results inline; older → disk reference."""
        # First run L1 for lossless gains.
        messages, dropped = self._layer1_snip(messages)

        tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        keep_inline = set(tool_indices[-3:])
        for idx in tool_indices:
            if idx in keep_inline:
                continue
            m = messages[idx]
            path = self._spill_to_disk("tool_result", m)
            orig_tokens = approx_tokens(str(m.get("content", "")))
            m["content"] = f"[spilled to disk: {path} ({orig_tokens} tokens)]"
        return messages, dropped

    # ── L3: CONTEXT_COLLAPSE (paragraph → git-log summary) ──

    def _layer3_collapse(self, messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
        """Collapse long assistant paragraphs into structured summaries.

        Strategy: keep first user intent + last 6 messages verbatim; every
        earlier assistant paragraph becomes ``* <first 80 chars> (...)``.
        """
        messages, dropped = self._layer2_microcompact(messages)

        if len(messages) <= 8:
            return messages, dropped

        keep_head = messages[:2]
        keep_tail = messages[-6:]
        middle = messages[2:-6]

        bullet_lines = []
        for m in middle:
            role = m.get("role", "?")
            c = str(m.get("content", "") or "")
            if not c:
                continue
            first = c.splitlines()[0][:120]
            bullet_lines.append(f"* [{role}] {first}")
            dropped += 1
        summary = {
            "role": "system",
            "content": (
                "### 历史消息摘要（L3 collapse）\n"
                + "\n".join(bullet_lines[:50])
                + (f"\n(... {max(0, len(bullet_lines) - 50)} 条省略)" if len(bullet_lines) > 50 else "")
            ),
        }
        return keep_head + [summary] + keep_tail, dropped

    # ── L4: AUTOCOMPACT (9-section structured rewrite) ──

    def _layer4_autocompact(self, messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
        """Nuclear compaction. 9-section structured summary.

        Extracts: user intent / decisions / files touched / errors /
        pending tasks / next step / recent files / todos.
        """
        # Run L3 first.
        messages, dropped = self._layer3_collapse(messages)

        first_user = next((m for m in messages if m.get("role") == "user"), None)
        recent_tail = messages[-8:]

        sections = {
            "1. user_intent": (first_user or {}).get("content", "") if first_user else "",
            "2. decisions": _extract_lines(messages, ["决定", "决策", "decided", "will use"]),
            "3. files_touched": _extract_lines(messages, ["wrote ", "edited ", "created ", ".py", ".md", ".dart"]),
            "4. errors_fixed": _extract_lines(messages, ["error", "fixed", "异常", "失败"]),
            "5. pending_tasks": _extract_lines(messages, ["TODO", "待办", "pending", "下一步"]),
            "6. next_step": (recent_tail[-1] if recent_tail else {}).get("content", "")[:400],
            "7. recent_files": "- see spilled artifacts in ~/.larkmentor/artifacts/",
        }

        summary_md = "## 会话摘要（L4 Autocompact）\n\n"
        for heading, body in sections.items():
            summary_md += f"### {heading}\n\n{body or '(none)'}\n\n"

        rewritten = [
            {"role": "system", "content": summary_md},
        ] + recent_tail
        dropped += max(0, len(messages) - len(rewritten))
        return rewritten, dropped

    # ── Helpers ──

    def _spill_to_disk(self, kind: str, m: Dict[str, Any]) -> str:
        ts = int(time.time() * 1000)
        name = f"{kind}_{ts}.json"
        path = os.path.join(self._artifact_dir, name)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return path


def _extract_lines(messages: List[Dict[str, Any]], keywords: List[str]) -> str:
    """Pull lines matching any keyword, dedupe, limit to 20 bullets."""
    out: List[str] = []
    seen = set()
    for m in messages:
        for line in str(m.get("content", "") or "").splitlines():
            lower = line.lower()
            if any(k.lower() in lower for k in keywords):
                stripped = line.strip()[:200]
                if stripped and stripped not in seen:
                    seen.add(stripped)
                    out.append(f"* {stripped}")
                    if len(out) >= 20:
                        return "\n".join(out)
    return "\n".join(out)
