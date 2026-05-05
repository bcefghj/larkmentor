"""Three-layer prompt cache for LLM cost optimization.

Claude Code architecture insight: split system prompt into 3 segments by
change frequency to maximize prompt cache hits:

Layer 1 (Static): Tool definitions, base personality, safety rules
    → Changes: never during session
    → Cache: always hit

Layer 2 (Session): Memory recall, AGENT_PILOT.md, skills metadata
    → Changes: once per session
    → Cache: high hit rate within session

Layer 3 (Dynamic): User message, current plan state, recent tool results
    → Changes: every turn
    → Cache: never cached
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("agent_pilot.prompt_cache")


@dataclass
class CacheEntry:
    key: str
    content: str
    created_at: float = field(default_factory=time.time)
    hit_count: int = 0
    char_count: int = 0

    def __post_init__(self) -> None:
        self.char_count = len(self.content)


class PromptCacheManager:
    """Manages 3-layer prompt cache for optimal LLM token usage."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._static_cache: Dict[str, CacheEntry] = {}
        self._session_cache: Dict[str, CacheEntry] = {}
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._stats = {"hits": 0, "misses": 0, "chars_saved": 0}

    def build_messages(
        self,
        *,
        static_parts: List[str],
        session_parts: List[str],
        dynamic_parts: List[Dict[str, str]],
        session_id: str = "default",
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Build optimized message list with cache-aware ordering.

        Returns (messages, cache_stats).
        """
        messages: List[Dict[str, Any]] = []

        # Layer 1: Static (tool defs, personality, safety)
        static_content = "\n\n".join(p for p in static_parts if p)
        if static_content:
            static_key = self._hash(static_content)
            cached = self._get_static(static_key)
            if cached:
                self._stats["hits"] += 1
                self._stats["chars_saved"] += cached.char_count
            else:
                self._set_static(static_key, static_content)
                self._stats["misses"] += 1
            messages.append({
                "role": "system",
                "content": static_content,
                "_cache_layer": "static",
            })

        # Layer 2: Session (memory, skills, user prefs)
        session_content = "\n\n".join(p for p in session_parts if p)
        if session_content:
            sess_key = f"{session_id}:{self._hash(session_content)}"
            cached = self._get_session(sess_key)
            if cached:
                self._stats["hits"] += 1
                self._stats["chars_saved"] += cached.char_count
            else:
                self._set_session(sess_key, session_content)
                self._stats["misses"] += 1
            messages.append({
                "role": "system",
                "content": session_content,
                "_cache_layer": "session",
            })

        # Layer 3: Dynamic (never cached)
        for msg in dynamic_parts:
            msg["_cache_layer"] = "dynamic"
            messages.append(msg)

        return messages, dict(self._stats)

    def get_stats(self) -> Dict[str, Any]:
        return dict(self._stats)

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            keys_to_remove = [
                k for k in self._session_cache if k.startswith(f"{session_id}:")
            ]
            for k in keys_to_remove:
                del self._session_cache[k]

    def clear_all(self) -> None:
        with self._lock:
            self._static_cache.clear()
            self._session_cache.clear()
            self._stats = {"hits": 0, "misses": 0, "chars_saved": 0}

    def _hash(self, content: str) -> str:
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def _get_static(self, key: str) -> Optional[CacheEntry]:
        with self._lock:
            entry = self._static_cache.get(key)
            if entry:
                entry.hit_count += 1
            return entry

    def _set_static(self, key: str, content: str) -> None:
        with self._lock:
            self._static_cache[key] = CacheEntry(key=key, content=content)

    def _get_session(self, key: str) -> Optional[CacheEntry]:
        with self._lock:
            entry = self._session_cache.get(key)
            if entry and (time.time() - entry.created_at) > self._ttl:
                del self._session_cache[key]
                return None
            if entry:
                entry.hit_count += 1
            return entry

    def _set_session(self, key: str, content: str) -> None:
        with self._lock:
            self._session_cache[key] = CacheEntry(key=key, content=content)


_default: Optional[PromptCacheManager] = None


def default_prompt_cache() -> PromptCacheManager:
    global _default
    if _default is None:
        _default = PromptCacheManager()
    return _default
