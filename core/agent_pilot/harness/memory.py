"""Persistent memory layer: LARKMENTOR.md + Mem0g / FlowMemory fallback.

Two memory tiers:

1. **System memory** – ``LARKMENTOR.md`` at repo root (additive, loaded on
   every session). This is our ``CLAUDE.md`` equivalent: company style,
   approval rules, sensitive domains. Never touched by compaction.

2. **Long-term memory** – Mem0g if available, otherwise fall back to the
   existing FlowMemory 6-tier hierarchy. Stores user preferences,
   historical decisions, action items, cross-session facts.

The memory layer exposes two operations:
* ``bootstrap(session_ctx)``  – returns system-prompt text to prepend.
* ``recall(intent, k=5)``     – semantic search over long-term.
* ``remember(fact, scope)``   – persist a new memory.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pilot.harness.memory")


@dataclass
class MemoryItem:
    content: str
    scope: str = "user"          # user / session / org / project
    tags: List[str] = field(default_factory=list)
    ts: int = 0


class MemoryLayer:
    def __init__(
        self,
        *,
        project_root: str = ".",
        memory_md_name: str = "LARKMENTOR.md",
        storage_dir: Optional[str] = None,
    ) -> None:
        self.project_root = os.path.abspath(project_root)
        self.memory_md_path = os.path.join(self.project_root, memory_md_name)
        self.storage_dir = storage_dir or os.path.expanduser("~/.larkmentor/memory")
        os.makedirs(self.storage_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._mem0: Optional[Any] = None
        self._try_init_mem0()

    # ── System memory (LARKMENTOR.md) ──

    def system_prompt_memory(self) -> str:
        """Return contents of LARKMENTOR.md verbatim (trimmed)."""
        if not os.path.exists(self.memory_md_path):
            return ""
        try:
            content = open(self.memory_md_path, "r", encoding="utf-8").read()
            return content.strip()[:12000]
        except Exception as exc:
            logger.warning("memory md read failed: %s", exc)
            return ""

    # ── Mem0 / FlowMemory recall ──

    def recall(self, intent: str, *, user_id: str = "default", k: int = 5) -> List[MemoryItem]:
        """Semantic recall. Returns empty list if no backend available."""
        if self._mem0 is not None:
            try:
                results = self._mem0.search(query=intent, user_id=user_id, limit=k)
                items: List[MemoryItem] = []
                for r in results.get("results", []) if isinstance(results, dict) else results or []:
                    if isinstance(r, dict):
                        items.append(MemoryItem(
                            content=str(r.get("memory") or r.get("text") or r),
                            scope="user",
                            tags=list((r.get("metadata") or {}).keys()),
                            ts=int(r.get("created_at") or time.time()),
                        ))
                if items:
                    return items
            except Exception as exc:
                logger.debug("mem0 recall failed: %s", exc)
        # Fallback: keyword search over local JSONL store.
        return self._local_recall(intent, user_id, k)

    def remember(self, content: str, *, user_id: str = "default",
                 scope: str = "user", tags: Optional[List[str]] = None) -> None:
        """Persist a memory item."""
        if self._mem0 is not None:
            try:
                self._mem0.add(content, user_id=user_id, metadata={"scope": scope, "tags": tags or []})
                return
            except Exception as exc:
                logger.debug("mem0 add failed: %s", exc)
        # Fallback: append to JSONL.
        self._local_remember(content, user_id, scope, tags or [])

    # ── Internal: Mem0 init ──

    def _try_init_mem0(self) -> None:
        if os.getenv("LARKMENTOR_DISABLE_MEM0") == "1":
            return
        try:
            from mem0 import Memory  # type: ignore
            self._mem0 = Memory()
            logger.info("mem0 memory backend initialised")
        except Exception as exc:
            logger.debug("mem0 unavailable: %s", exc)
            self._mem0 = None

    # ── Internal: local JSONL fallback ──

    def _user_path(self, user_id: str) -> str:
        safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in user_id)[:64] or "default"
        return os.path.join(self.storage_dir, f"{safe}.jsonl")

    def _local_remember(self, content: str, user_id: str, scope: str, tags: List[str]) -> None:
        import json
        path = self._user_path(user_id)
        entry = {
            "ts": int(time.time()),
            "content": content,
            "scope": scope,
            "tags": tags,
        }
        try:
            with self._lock:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("local memory write failed: %s", exc)

    def _local_recall(self, intent: str, user_id: str, k: int) -> List[MemoryItem]:
        import json
        path = self._user_path(user_id)
        if not os.path.exists(path):
            return []
        terms = [t for t in intent.lower().split() if len(t) > 1]
        matches: List[Any] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-500:]
            for line in lines:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                text = str(obj.get("content", "")).lower()
                score = sum(1 for t in terms if t in text)
                if score > 0:
                    matches.append((score, obj))
        except Exception as exc:
            logger.warning("local memory read failed: %s", exc)
            return []
        matches.sort(key=lambda x: (-x[0], -int(x[1].get("ts", 0))))
        out: List[MemoryItem] = []
        for _, obj in matches[:k]:
            out.append(MemoryItem(
                content=str(obj.get("content", "")),
                scope=str(obj.get("scope", "user")),
                tags=list(obj.get("tags") or []),
                ts=int(obj.get("ts", 0)),
            ))
        return out


_default: Optional[MemoryLayer] = None
_default_lock = threading.Lock()


def default_memory() -> MemoryLayer:
    global _default
    with _default_lock:
        if _default is None:
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            root = os.path.dirname(root)  # up past core/
            _default = MemoryLayer(project_root=root)
        return _default
