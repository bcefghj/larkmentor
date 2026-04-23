"""Multi-Provider Router (4 家模型) + Cost Budget

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

Cost budget：per plan 0.5 CNY，超预算降级到 DeepSeek。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent.providers")


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
        cost_input_per_1m=0.8, cost_output_per_1m=2.0,
        speed_tps=80, context_window=32_768,
        strength=["chinese", "fast"],
    ),
    "minimax": ProviderConfig(
        name="minimax",
        endpoint="https://api.minimax.chat/v1",
        api_key_env="MINIMAX_API_KEY",
        model=os.getenv("MINIMAX_MODEL", "MiniMax-M2"),
        cost_input_per_1m=0.30, cost_output_per_1m=1.20,
        speed_tps=46, context_window=205_000,
        strength=["reasoning", "long_context", "planning"],
    ),
    "deepseek": ProviderConfig(
        name="deepseek",
        endpoint="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        cost_input_per_1m=0.14, cost_output_per_1m=0.28,
        speed_tps=60, context_window=65_536,
        strength=["cheap", "summary"],
    ),
    "kimi": ProviderConfig(
        name="kimi",
        endpoint="https://api.moonshot.cn/v1",
        api_key_env="KIMI_API_KEY",
        model=os.getenv("KIMI_MODEL", "moonshot-v1-128k"),
        cost_input_per_1m=12.0, cost_output_per_1m=12.0,
        speed_tps=40, context_window=128_000,
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
        self._load_config()

    def _load_config(self) -> None:
        """Load .larkmentor/models.yaml if exists."""
        cfg_path = Path.cwd() / ".larkmentor" / "models.yaml"
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

    def pick(self, task_kind: str = "default") -> Optional[ProviderConfig]:
        name = self.routing.get(task_kind, self.routing.get("default", "doubao"))
        cfg = self.configs.get(name)
        if cfg and cfg.enabled and os.getenv(cfg.api_key_env):
            return cfg
        # Fallback chain
        for fb in self.fallback:
            cfg = self.configs.get(fb)
            if cfg and cfg.enabled and os.getenv(cfg.api_key_env):
                return cfg
        return None

    def chat(
        self, messages: List[Dict[str, Any]], *,
        task_kind: str = "default",
        temperature: float = 0.4,
        max_tokens: int = 1500,
        tools: Optional[List[Dict]] = None,
    ) -> str:
        """Route to appropriate provider and make the call."""
        # Budget check
        if self._current_plan_cost_cny >= self.per_plan_budget:
            task_kind = "summary"  # downgrade to cheapest
            logger.warning("budget exceeded %.3f >= %.3f, downgrading to %s",
                           self._current_plan_cost_cny, self.per_plan_budget, task_kind)

        cfg = self.pick(task_kind)
        if not cfg:
            logger.error("no provider available for task=%s", task_kind)
            return ""

        try:
            text, input_tokens, output_tokens = self._openai_compatible_call(
                cfg, messages, temperature=temperature, max_tokens=max_tokens, tools=tools,
            )
            # Track cost
            cost = (input_tokens / 1_000_000) * cfg.cost_input_per_1m + \
                   (output_tokens / 1_000_000) * cfg.cost_output_per_1m
            with self._lock:
                self._current_plan_cost_cny += cost
                self.usage.append(UsageRecord(
                    provider=cfg.name, model=cfg.model,
                    input_tokens=input_tokens, output_tokens=output_tokens,
                    cost_cny=cost, task_kind=task_kind,
                ))
                if len(self.usage) > 1000:
                    self.usage = self.usage[-1000:]
            return text
        except Exception as e:
            logger.warning("provider %s failed: %s; trying fallback", cfg.name, e)
            # Try next in chain
            for fb in self.fallback:
                if fb == cfg.name:
                    continue
                fb_cfg = self.configs.get(fb)
                if fb_cfg and fb_cfg.enabled and os.getenv(fb_cfg.api_key_env):
                    try:
                        text, itok, otok = self._openai_compatible_call(
                            fb_cfg, messages, temperature=temperature, max_tokens=max_tokens, tools=tools,
                        )
                        return text
                    except Exception as e2:
                        logger.debug("fallback %s also failed: %s", fb, e2)
                        continue
            return ""

    def _openai_compatible_call(
        self, cfg: ProviderConfig, messages: List[Dict], *,
        temperature: float, max_tokens: int, tools: Optional[List[Dict]] = None,
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

    def reset_plan_budget(self) -> None:
        with self._lock:
            self._current_plan_cost_cny = 0.0

    def current_plan_cost(self) -> float:
        return self._current_plan_cost_cny

    def daily_cost(self) -> float:
        from datetime import datetime
        start_of_day = datetime.now().replace(hour=0, minute=0, second=0).timestamp()
        return sum(u.cost_cny for u in self.usage if u.ts >= start_of_day)

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
                } for name, c in self.configs.items()
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
                {"provider": u.provider, "model": u.model,
                 "input": u.input_tokens, "output": u.output_tokens,
                 "cost": round(u.cost_cny, 5), "task": u.task_kind}
                for u in self.usage[-10:]
            ],
        }


_singleton: Optional[ProviderRouter] = None


def default_providers() -> ProviderRouter:
    global _singleton
    if _singleton is None:
        _singleton = ProviderRouter()
    return _singleton
