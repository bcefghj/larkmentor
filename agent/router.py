"""Strategy Router · 8 种执行策略自动路由（对齐 Shannon）

基于意图复杂度 0-1 自动选择策略：
- Simple (<0.3): 单 agent 直出
- DAG (默认): Fan-out/fan-in + 拓扑排序
- ReAct: Reason→Act→Observe 迭代
- Research: 分层模型（省 50-70% 成本）
- Exploratory: Tree-of-Thoughts 并行假设
- Swarm: Lead + 工作者 + 收敛检测
- Browser: Playwright headless
- Domain: 专家 subagent + 领域 prompt
"""

from __future__ import annotations

import enum
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent.router")


class Strategy(str, enum.Enum):
    SIMPLE = "simple"
    DAG = "dag"
    REACT = "react"
    RESEARCH = "research"
    EXPLORATORY = "exploratory"
    SWARM = "swarm"
    BROWSER = "browser"
    DOMAIN = "domain"


@dataclass
class RouteDecision:
    strategy: Strategy
    complexity: float  # 0-1
    reasoning: str
    rationale: List[str]
    recommended_agents: List[str]


# Keyword signals for complexity estimation
SIGNALS = {
    "multi_step": [r"然后", r"接着", r"先.*再", r"最后", r"and then", r"after that", r"step by step"],
    "iteration": [r"多次", r"反复", r"迭代", r"直到", r"loop", r"iterate", r"until"],
    "debate": [r"讨论", r"辩论", r"对比", r"方案.*选", r"pros\s*(and|&)\s*cons", r"debate"],
    "research": [r"调研", r"研究", r"分析", r"收集", r"整理", r"research", r"analy[sz]e", r"gather"],
    "exploratory": [r"尝试", r"探索", r"brainstorm", r"创意", r"多种", r"several options"],
    "browser": [r"网页", r"搜索", r"查找", r"browse", r"search online", r"web"],
    "domain_specific": [r"合规", r"法律", r"安全审计", r"compliance", r"legal", r"security audit"],
}


class StrategyRouter:
    def __init__(self) -> None:
        pass

    def route(self, intent: str, *, context: Optional[Dict[str, Any]] = None) -> RouteDecision:
        """Analyze intent + return strategy."""
        intent_lower = intent.lower()
        rationale: List[str] = []

        # Compute signal scores
        multi_step = self._match(SIGNALS["multi_step"], intent_lower)
        iteration = self._match(SIGNALS["iteration"], intent_lower)
        debate = self._match(SIGNALS["debate"], intent_lower)
        research = self._match(SIGNALS["research"], intent_lower)
        exploratory = self._match(SIGNALS["exploratory"], intent_lower)
        browser = self._match(SIGNALS["browser"], intent_lower)
        domain_specific = self._match(SIGNALS["domain_specific"], intent_lower)

        # Length-based signal
        length_signal = min(1.0, len(intent) / 200)
        rationale.append(f"length_signal={length_signal:.2f}")

        # Complexity estimate
        complexity = 0.1
        complexity += 0.3 if multi_step else 0.0
        complexity += 0.3 if iteration else 0.0
        complexity += 0.25 if research else 0.0
        complexity += 0.2 if exploratory else 0.0
        complexity += 0.2 if debate else 0.0
        complexity += length_signal * 0.15
        complexity = min(1.0, complexity)
        rationale.append(f"complexity={complexity:.2f}")

        # Strategy selection
        strategy = Strategy.DAG  # default
        recommended: List[str] = []

        if domain_specific:
            strategy = Strategy.DOMAIN
            recommended = ["@domain-expert", "@verifier"]
            rationale.append("matched domain_specific")
        elif debate:
            strategy = Strategy.SWARM
            recommended = ["@lead", "@pro-debater", "@con-debater", "@convergence-judge"]
            rationale.append("matched debate signal → Swarm")
        elif exploratory:
            strategy = Strategy.EXPLORATORY
            recommended = ["@idea-generator-1", "@idea-generator-2", "@idea-generator-3", "@pruner"]
            rationale.append("matched exploratory → Tree-of-Thoughts")
        elif browser:
            strategy = Strategy.BROWSER
            recommended = ["@browser-agent"]
            rationale.append("matched browser signal")
        elif research:
            strategy = Strategy.RESEARCH
            recommended = ["@researcher", "@summarizer"]
            rationale.append("matched research → tiered model")
        elif iteration:
            strategy = Strategy.REACT
            recommended = ["@reasoner"]
            rationale.append("matched iteration → ReAct loop")
        elif complexity < 0.3:
            strategy = Strategy.SIMPLE
            recommended = ["@responder"]
            rationale.append(f"low complexity → Simple")
        else:
            strategy = Strategy.DAG
            recommended = ["@planner", "@workers(3)"]
            rationale.append(f"mid complexity → DAG")

        return RouteDecision(
            strategy=strategy, complexity=complexity,
            reasoning=" ".join(rationale),
            rationale=rationale, recommended_agents=recommended,
        )

    def _match(self, patterns: List[str], text: str) -> bool:
        for p in patterns:
            if re.search(p, text, re.IGNORECASE):
                return True
        return False


_singleton: Optional[StrategyRouter] = None


def default_router() -> StrategyRouter:
    global _singleton
    if _singleton is None:
        _singleton = StrategyRouter()
    return _singleton
