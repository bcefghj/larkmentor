"""Multi-Provider Router (4 家模型) + Dynamic Routing + Cost Budget

支持：
- 豆包（Volcano Ark）
- MiniMax M2.7（用户提供，97 百分位智商，205K context）
- DeepSeek（便宜 5x，做 summary/审查）
- Kimi（128K 长 context）

路由：
- planning/reasoning → MiniMax M2.7
- chinese_chat → 豆包
- summary → DeepSeek
- long_context → Kimi
- fallback_chain: [minimax, doubao, deepseek, kimi]

Dynamic routing:
- score = success_rate * 0.4 + (1/latency_p95) * 0.3 + (1/cost) * 0.3
- Falls back to static routing when insufficient data (<10 calls)

Health checks:
- Provider marked "degraded" after 3 consecutive failures
- Auto-recover after 60s

Cost budget：per plan 0.5 CNY，超预算降级到 DeepSeek。
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("agent.providers")

STATS_FILE = Path.cwd() / ".agent-pilot" / "provider_stats.json"
SLIDING_WINDOW_SIZE = 100
HEALTH_CONSECUTIVE_FAILURES = 3
HEALTH_RECOVERY_SEC = 60.0
MIN_CALLS_FOR_DYNAMIC = 10


@dataclass
class ProviderConfig:
    name: str
    endpoint: str
    api_key_env: str
    model: str
    cost_input_per_1m: float = 0.0
    cost_output_per_1m: float = 0.0
    speed_tps: int = 50
    context_window: int = 128_000
    strength: List[str] = field(default_factory=list)
    openai_compatible: bool = True
    enabled: bool = True


DEFAULT_CONFIGS: Dict[str, ProviderConfig] = {
    "doubao": ProviderConfig(
        name="doubao",
        endpoint="https://ark.cn-beijing.volces.com/api/v3",
        api_key_env="DOUBAO_API_KEY",
        model=os.getenv("DOUBAO_MODEL", "doubao-1-5-pro-32k-250115"),
        cost_input_per_1m=0.8,
        cost_output_per_1m=2.0,
        speed_tps=80,
        context_window=32_768,
        strength=["chinese", "fast"],
    ),
    "minimax": ProviderConfig(
        name="minimax",
        endpoint="https://api.minimax.chat/v1",
        api_key_env="MINIMAX_API_KEY",
        model=os.getenv("MINIMAX_MODEL", "MiniMax-M2"),
        cost_input_per_1m=0.30,
        cost_output_per_1m=1.20,
        speed_tps=46,
        context_window=205_000,
        strength=["reasoning", "long_context", "planning"],
    ),
    "deepseek": ProviderConfig(
        name="deepseek",
        endpoint="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        cost_input_per_1m=0.14,
        cost_output_per_1m=0.28,
        speed_tps=60,
        context_window=65_536,
        strength=["cheap", "summary"],
    ),
    "kimi": ProviderConfig(
        name="kimi",
        endpoint="https://api.moonshot.cn/v1",
        api_key_env="KIMI_API_KEY",
        model=os.getenv("KIMI_MODEL", "moonshot-v1-128k"),
        cost_input_per_1m=12.0,
        cost_output_per_1m=12.0,
        speed_tps=40,
        context_window=128_000,
        strength=["long_doc", "128k"],
    ),
}

DEFAULT_ROUTING = {
    "planning": "minimax",
    "reasoning": "minimax",
    "summary": "deepseek",
    "long_context": "kimi",
    "chinese_chat": "doubao",
    "default": "doubao",
    "review": "deepseek",
    "critique": "deepseek",
    "research": "kimi",
    "validation": "deepseek",
}

DEFAULT_FALLBACK = ["minimax", "doubao", "deepseek", "kimi"]


@dataclass
class UsageRecord:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_cny: float
    ts: float = field(default_factory=time.time)
    task_kind: str = ""


@dataclass
class CallRecord:
    """Single call outcome for sliding-window tracking."""

    success: bool
    latency_ms: float
    cost_cny: float
    ts: float = field(default_factory=time.time)


@dataclass
class ProviderHealth:
    """Health state for a single provider."""

    consecutive_failures: int = 0
    degraded_since: Optional[float] = None
    total_calls: int = 0
    total_successes: int = 0

    @property
    def is_degraded(self) -> bool:
        if self.degraded_since is None:
            return False
        if time.time() - self.degraded_since >= HEALTH_RECOVERY_SEC:
            self.consecutive_failures = 0
            self.degraded_since = None
            return False
        return True

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.degraded_since = None
        self.total_calls += 1
        self.total_successes += 1

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self.total_calls += 1
        if self.consecutive_failures >= HEALTH_CONSECUTIVE_FAILURES:
            self.degraded_since = time.time()


class ProviderRouter:
    def __init__(self, *, per_plan_budget_cny: float = 0.5, daily_cap_cny: float = 20.0) -> None:
        self.configs: Dict[str, ProviderConfig] = dict(DEFAULT_CONFIGS)
        self.routing: Dict[str, str] = dict(DEFAULT_ROUTING)
        self.fallback: List[str] = list(DEFAULT_FALLBACK)
        self.per_plan_budget = per_plan_budget_cny
        self.daily_cap = daily_cap_cny
        self.usage: List[UsageRecord] = []
        self._lock = threading.Lock()
        self._current_plan_cost_cny = 0.0

        # --- Dynamic routing state ---
        # provider_name -> task_kind -> deque of CallRecord (sliding window)
        self._call_history: Dict[str, Dict[str, deque]] = {}
        # provider_name -> ProviderHealth
        self._health: Dict[str, ProviderHealth] = {}

        for name in self.configs:
            self._call_history[name] = {}
            self._health[name] = ProviderHealth()

        self._load_config()
        self._load_stats()

    # ─── Config loading ───────────────────────────────────────────────────

    def _load_config(self) -> None:
        """Load .agent-pilot/models.yaml if exists."""
        cfg_path = Path.cwd() / ".agent-pilot" / "models.yaml"
        if not cfg_path.exists():
            return
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(cfg_path.read_text())
            for name, pc in (data.get("providers") or {}).items():
                if name in self.configs:
                    c = self.configs[name]
                    if pc.get("model"):
                        c.model = pc["model"]
                    if pc.get("endpoint"):
                        c.endpoint = pc["endpoint"]
                    if "cost_per_1m" in pc:
                        c.cost_input_per_1m = pc["cost_per_1m"].get("input", c.cost_input_per_1m)
                        c.cost_output_per_1m = pc["cost_per_1m"].get("output", c.cost_output_per_1m)
                    if "enabled" in pc:
                        c.enabled = pc["enabled"]
            if "routing" in data:
                self.routing.update(data["routing"])
            if "budget" in data:
                self.per_plan_budget = data["budget"].get("per_plan_cny", self.per_plan_budget)
                self.daily_cap = data["budget"].get("daily_cap_cny", self.daily_cap)
            logger.info("provider config loaded from %s", cfg_path)
        except ImportError:
            logger.debug("yaml not installed, skipping models.yaml")
        except Exception as e:
            logger.warning("models.yaml load failed: %s", e)

    # ─── Persistent stats ─────────────────────────────────────────────────

    def _load_stats(self) -> None:
        """Load routing stats from JSON file."""
        if not STATS_FILE.exists():
            return
        try:
            data = json.loads(STATS_FILE.read_text(encoding="utf-8"))
            for provider_name, task_map in data.get("call_history", {}).items():
                if provider_name not in self._call_history:
                    self._call_history[provider_name] = {}
                for task_kind, records in task_map.items():
                    dq = deque(maxlen=SLIDING_WINDOW_SIZE)
                    for r in records[-SLIDING_WINDOW_SIZE:]:
                        dq.append(
                            CallRecord(
                                success=r["success"],
                                latency_ms=r["latency_ms"],
                                cost_cny=r["cost_cny"],
                                ts=r["ts"],
                            )
                        )
                    self._call_history[provider_name][task_kind] = dq
            for provider_name, h in data.get("health", {}).items():
                if provider_name in self._health:
                    self._health[provider_name].total_calls = h.get("total_calls", 0)
                    self._health[provider_name].total_successes = h.get("total_successes", 0)
            logger.info("provider stats loaded from %s", STATS_FILE)
        except Exception as e:
            logger.warning("failed to load provider stats: %s", e)

    def save_stats(self) -> None:
        """Persist routing stats to JSON file."""
        try:
            STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "call_history": {},
                "health": {},
            }
            with self._lock:
                for provider_name, task_map in self._call_history.items():
                    data["call_history"][provider_name] = {}
                    for task_kind, dq in task_map.items():
                        data["call_history"][provider_name][task_kind] = [
                            {"success": r.success, "latency_ms": r.latency_ms, "cost_cny": r.cost_cny, "ts": r.ts}
                            for r in dq
                        ]
                for provider_name, h in self._health.items():
                    data["health"][provider_name] = {
                        "total_calls": h.total_calls,
                        "total_successes": h.total_successes,
                    }
            STATS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("failed to save provider stats: %s", e)

    # ─── Metrics ──────────────────────────────────────────────────────────

    def _get_window(self, provider: str, task_kind: str) -> deque:
        """Get or create the sliding window for a provider/task_kind."""
        task_map = self._call_history.setdefault(provider, {})
        if task_kind not in task_map:
            task_map[task_kind] = deque(maxlen=SLIDING_WINDOW_SIZE)
        return task_map[task_kind]

    def _record_call(self, provider: str, task_kind: str, success: bool, latency_ms: float, cost_cny: float) -> None:
        """Record a call outcome into sliding window and health tracker."""
        with self._lock:
            window = self._get_window(provider, task_kind)
            window.append(
                CallRecord(
                    success=success,
                    latency_ms=latency_ms,
                    cost_cny=cost_cny,
                )
            )
            health = self._health.setdefault(provider, ProviderHealth())
            if success:
                health.record_success()
            else:
                health.record_failure()

    def _success_rate(self, provider: str, task_kind: str) -> Tuple[float, int]:
        """Return (success_rate, total_calls) for provider+task_kind window."""
        window = self._get_window(provider, task_kind)
        if not window:
            return 1.0, 0
        successes = sum(1 for r in window if r.success)
        return successes / len(window), len(window)

    def _latency_percentiles(self, provider: str, task_kind: str) -> Dict[str, float]:
        """Return p50/p95/p99 latency in ms for the sliding window."""
        window = self._get_window(provider, task_kind)
        latencies = [r.latency_ms for r in window if r.success]
        if not latencies:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
        latencies_sorted = sorted(latencies)
        n = len(latencies_sorted)
        return {
            "p50": latencies_sorted[n // 2],
            "p95": latencies_sorted[min(int(n * 0.95), n - 1)],
            "p99": latencies_sorted[min(int(n * 0.99), n - 1)],
        }

    def _avg_cost(self, provider: str, task_kind: str) -> float:
        """Average cost per call in the window."""
        window = self._get_window(provider, task_kind)
        if not window:
            cfg = self.configs.get(provider)
            if cfg:
                return (cfg.cost_input_per_1m + cfg.cost_output_per_1m) / 2.0
            return 1.0
        return statistics.mean(r.cost_cny for r in window) if window else 1.0

    # ─── Dynamic scoring ──────────────────────────────────────────────────

    def _score_provider(self, provider: str, task_kind: str) -> float:
        """Compute dynamic routing score for a provider.

        score = success_rate * 0.4 + (1/latency_p95) * 0.3 + (1/cost) * 0.3
        All terms normalized to [0, 1] range.
        """
        sr, count = self._success_rate(provider, task_kind)
        if count < MIN_CALLS_FOR_DYNAMIC:
            return -1.0  # sentinel: insufficient data

        percs = self._latency_percentiles(provider, task_kind)
        p95 = percs["p95"] if percs["p95"] > 0 else 1.0
        cost = self._avg_cost(provider, task_kind)
        if cost <= 0:
            cost = 0.001

        latency_score = min(1.0, 1000.0 / p95)
        cost_score = min(1.0, 0.5 / cost)

        return sr * 0.4 + latency_score * 0.3 + cost_score * 0.3

    # ─── Provider selection ───────────────────────────────────────────────

    def pick(self, task_kind: str = "default") -> Optional[ProviderConfig]:
        """Pick provider using dynamic scoring, falling back to static routing."""
        # Try dynamic routing first
        best_score = -1.0
        best_name: Optional[str] = None

        for name, cfg in self.configs.items():
            if not cfg.enabled or not os.getenv(cfg.api_key_env):
                continue
            health = self._health.get(name)
            if health and health.is_degraded:
                continue
            score = self._score_provider(name, task_kind)
            if score > best_score:
                best_score = score
                best_name = name

        if best_score > 0 and best_name:
            return self.configs[best_name]

        # Static routing fallback
        name = self.routing.get(task_kind, self.routing.get("default", "doubao"))
        cfg = self.configs.get(name)
        if cfg and cfg.enabled and os.getenv(cfg.api_key_env):
            health = self._health.get(name)
            if not (health and health.is_degraded):
                return cfg

        # Fallback chain
        for fb in self.fallback:
            cfg = self.configs.get(fb)
            if cfg and cfg.enabled and os.getenv(cfg.api_key_env):
                health = self._health.get(fb)
                if not (health and health.is_degraded):
                    return cfg

        # Last resort: pick any available (even degraded)
        for fb in self.fallback:
            cfg = self.configs.get(fb)
            if cfg and cfg.enabled and os.getenv(cfg.api_key_env):
                return cfg
        return None

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        task_kind: str = "default",
        temperature: float = 0.4,
        max_tokens: int = 1500,
        tools: Optional[List[Dict]] = None,
    ) -> str:
        """Route to appropriate provider and make the call."""
        # Cost circuit breaker: per-plan budget check
        if self._current_plan_cost_cny >= self.per_plan_budget:
            task_kind = "summary"
            logger.warning(
                "budget exceeded %.3f >= %.3f, downgrading to cheapest",
                self._current_plan_cost_cny,
                self.per_plan_budget,
            )

        cfg = self.pick(task_kind)
        if not cfg:
            logger.error("no provider available for task=%s", task_kind)
            return ""

        try:
            t0 = time.time()
            text, input_tokens, output_tokens = self._openai_compatible_call(
                cfg,
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
            )
            latency_ms = (time.time() - t0) * 1000

            cost = (input_tokens / 1_000_000) * cfg.cost_input_per_1m + (
                output_tokens / 1_000_000
            ) * cfg.cost_output_per_1m

            with self._lock:
                self._current_plan_cost_cny += cost
                self.usage.append(
                    UsageRecord(
                        provider=cfg.name,
                        model=cfg.model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_cny=cost,
                        task_kind=task_kind,
                    )
                )
                if len(self.usage) > 1000:
                    self.usage = self.usage[-1000:]

            self._record_call(cfg.name, task_kind, success=True, latency_ms=latency_ms, cost_cny=cost)
            return text

        except Exception as e:
            latency_ms = (time.time() - t0) * 1000 if "t0" in dir() else 0.0
            self._record_call(cfg.name, task_kind, success=False, latency_ms=latency_ms, cost_cny=0.0)
            logger.warning("provider %s failed: %s; trying fallback", cfg.name, e)

            for fb in self.fallback:
                if fb == cfg.name:
                    continue
                fb_cfg = self.configs.get(fb)
                if not fb_cfg or not fb_cfg.enabled or not os.getenv(fb_cfg.api_key_env):
                    continue
                health = self._health.get(fb)
                if health and health.is_degraded:
                    continue
                try:
                    t0_fb = time.time()
                    text, itok, otok = self._openai_compatible_call(
                        fb_cfg,
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        tools=tools,
                    )
                    fb_latency = (time.time() - t0_fb) * 1000
                    fb_cost = (itok / 1_000_000) * fb_cfg.cost_input_per_1m + (
                        otok / 1_000_000
                    ) * fb_cfg.cost_output_per_1m
                    self._record_call(fb_cfg.name, task_kind, success=True, latency_ms=fb_latency, cost_cny=fb_cost)
                    return text
                except Exception as e2:
                    self._record_call(fb, task_kind, success=False, latency_ms=0.0, cost_cny=0.0)
                    logger.debug("fallback %s also failed: %s", fb, e2)
                    continue
            return ""

    def _openai_compatible_call(
        self,
        cfg: ProviderConfig,
        messages: List[Dict],
        *,
        temperature: float,
        max_tokens: int,
        tools: Optional[List[Dict]] = None,
    ):
        """OpenAI-compatible chat completion call. Works for Doubao, MiniMax, DeepSeek, Kimi."""
        try:
            import requests
        except ImportError:
            raise RuntimeError("requests not installed")

        api_key = os.getenv(cfg.api_key_env, "")
        if not api_key:
            raise RuntimeError(f"{cfg.api_key_env} not set")

        url = f"{cfg.endpoint.rstrip('/')}/chat/completions"
        payload = {
            "model": cfg.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"http {r.status_code}: {r.text[:400]}")
        data = r.json()
        content = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage") or {}
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        return content, input_tokens, output_tokens

    # ─── Budget management ────────────────────────────────────────────────

    def reset_plan_budget(self) -> None:
        with self._lock:
            self._current_plan_cost_cny = 0.0

    def current_plan_cost(self) -> float:
        return self._current_plan_cost_cny

    def daily_cost(self) -> float:
        from datetime import datetime

        start_of_day = datetime.now().replace(hour=0, minute=0, second=0).timestamp()
        return sum(u.cost_cny for u in self.usage if u.ts >= start_of_day)

    # ─── Metrics export ───────────────────────────────────────────────────

    def get_provider_stats(self) -> Dict[str, Any]:
        """Return structured health and performance data for all providers."""
        stats: Dict[str, Any] = {}
        for name in self.configs:
            health = self._health.get(name, ProviderHealth())
            task_stats = {}
            for task_kind, window in self._call_history.get(name, {}).items():
                if not window:
                    continue
                sr, count = self._success_rate(name, task_kind)
                percs = self._latency_percentiles(name, task_kind)
                avg_cost = self._avg_cost(name, task_kind)
                task_stats[task_kind] = {
                    "call_count": count,
                    "success_rate": round(sr, 4),
                    "latency_p50_ms": round(percs["p50"], 1),
                    "latency_p95_ms": round(percs["p95"], 1),
                    "latency_p99_ms": round(percs["p99"], 1),
                    "avg_cost_cny": round(avg_cost, 6),
                    "dynamic_score": round(self._score_provider(name, task_kind), 4),
                }
            stats[name] = {
                "enabled": self.configs[name].enabled,
                "has_key": bool(os.getenv(self.configs[name].api_key_env)),
                "is_degraded": health.is_degraded,
                "consecutive_failures": health.consecutive_failures,
                "total_calls": health.total_calls,
                "total_successes": health.total_successes,
                "lifetime_success_rate": (
                    round(health.total_successes / health.total_calls, 4) if health.total_calls > 0 else None
                ),
                "task_stats": task_stats,
            }
        return stats

    def snapshot(self) -> Dict[str, Any]:
        return {
            "providers": {
                name: {
                    "enabled": c.enabled,
                    "model": c.model,
                    "context_window": c.context_window,
                    "has_key": bool(os.getenv(c.api_key_env)),
                    "strength": c.strength,
                    "cost_input": c.cost_input_per_1m,
                    "cost_output": c.cost_output_per_1m,
                    "is_degraded": self._health.get(name, ProviderHealth()).is_degraded,
                }
                for name, c in self.configs.items()
            },
            "routing": self.routing,
            "fallback": self.fallback,
            "budget": {
                "per_plan_cny": self.per_plan_budget,
                "daily_cap_cny": self.daily_cap,
                "current_plan_cost": self._current_plan_cost_cny,
                "daily_cost": self.daily_cost(),
            },
            "recent_usage": [
                {
                    "provider": u.provider,
                    "model": u.model,
                    "input": u.input_tokens,
                    "output": u.output_tokens,
                    "cost": round(u.cost_cny, 5),
                    "task": u.task_kind,
                }
                for u in self.usage[-10:]
            ],
            "health": self.get_provider_stats(),
        }


_singleton: Optional[ProviderRouter] = None


def default_providers() -> ProviderRouter:
    global _singleton
    if _singleton is None:
        _singleton = ProviderRouter()
    return _singleton
