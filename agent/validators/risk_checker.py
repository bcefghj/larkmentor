"""Risk Checker · 为规划结果找依赖冲突/资源竞争/潜在失败点。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent.validators.risk")


@dataclass
class RiskReport:
    high_risk: List[str] = field(default_factory=list)
    medium_risk: List[str] = field(default_factory=list)
    low_risk: List[str] = field(default_factory=list)
    overall_score: float = 0.0  # 0 worst, 1 safest


class RiskChecker:
    def check_plan(self, plan: Dict[str, Any]) -> RiskReport:
        report = RiskReport()
        steps = plan.get("steps", [])
        tool_counts: Dict[str, int] = {}
        for s in steps:
            tool = s.get("tool", "")
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
            # High-risk tools
            if any(kw in tool for kw in ("delete", "batch_send", "clear", "reject", "overwrite")):
                report.high_risk.append(f"high-risk tool: {tool} at {s.get('step_id', '?')}")
            if tool_counts[tool] > 5:
                report.medium_risk.append(f"tool {tool} called {tool_counts[tool]} times (possible loop)")

        # Check for cycles in deps
        step_ids = {s.get("step_id") for s in steps}
        for s in steps:
            deps = s.get("depends_on", [])
            for d in deps:
                if d not in step_ids:
                    report.medium_risk.append(f"dangling dep: {s.get('step_id')} → {d}")

        # Aggregate score
        score = 1.0 - 0.3 * len(report.high_risk) - 0.1 * len(report.medium_risk)
        report.overall_score = max(0.0, score)
        return report


_singleton: Optional[RiskChecker] = None


def default_risk_checker() -> RiskChecker:
    global _singleton
    if _singleton is None:
        _singleton = RiskChecker()
    return _singleton
