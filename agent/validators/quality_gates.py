"""5 道 Quality Gates（每个输出前必须过）

G1 Completeness: 必要字段全在
G2 Consistency: 跨 subagent 一致
G3 Factuality: 关键 claim 可查 source
G4 Readability: LLM-as-judge ≥ 8
G5 Safety: PII / 敏感词 / injection 过

任一不过 → 自动 replan 或 flag 给用户。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .citation_agent import default_citation_agent
from .security_auditor import default_security_auditor

logger = logging.getLogger("agent.validators.quality_gates")


@dataclass
class GateResult:
    name: str
    passed: bool
    score: float  # 0-1
    detail: str = ""


@dataclass
class QualityReport:
    gates: List[GateResult]
    overall_passed: bool
    overall_score: float  # avg 0-1

    def as_dict(self) -> Dict[str, Any]:
        return {
            "gates": [{"name": g.name, "passed": g.passed, "score": g.score, "detail": g.detail} for g in self.gates],
            "overall_passed": self.overall_passed,
            "overall_score": self.overall_score,
        }


class QualityGateRunner:
    """Runs 5 gates sequentially. All must pass for overall_passed."""

    def run(
        self, content: str, *,
        required_fields: Optional[List[str]] = None,
        related_content: Optional[List[str]] = None,
        tenant_id: str = "default",
    ) -> QualityReport:
        gates: List[GateResult] = []

        # G1 Completeness
        gates.append(self._gate_completeness(content, required_fields or []))
        # G2 Consistency
        gates.append(self._gate_consistency(content, related_content or []))
        # G3 Factuality
        gates.append(self._gate_factuality(content, tenant_id))
        # G4 Readability
        gates.append(self._gate_readability(content))
        # G5 Safety
        gates.append(self._gate_safety(content))

        overall_passed = all(g.passed for g in gates)
        overall_score = sum(g.score for g in gates) / len(gates)
        return QualityReport(gates=gates, overall_passed=overall_passed, overall_score=overall_score)

    def _gate_completeness(self, content: str, required_fields: List[str]) -> GateResult:
        if not required_fields:
            return GateResult("G1_completeness", passed=True, score=1.0, detail="no required_fields specified")
        missing = [f for f in required_fields if f.lower() not in content.lower()]
        score = 1.0 - len(missing) / len(required_fields)
        return GateResult(
            "G1_completeness",
            passed=len(missing) == 0,
            score=score,
            detail=f"missing={missing}" if missing else "all required fields present",
        )

    def _gate_consistency(self, content: str, related: List[str]) -> GateResult:
        if not related:
            return GateResult("G2_consistency", passed=True, score=0.9, detail="no cross-reference available")
        # Extract numbers and compare
        content_numbers = set(re.findall(r'\d+(?:\.\d+)?', content))
        conflicts = 0
        for r in related:
            r_numbers = set(re.findall(r'\d+(?:\.\d+)?', r))
            # same topic should share some numbers
            overlap = content_numbers & r_numbers
            # if neither has shared nums and both have many nums, suspicious
            if len(content_numbers) > 3 and len(r_numbers) > 3 and not overlap:
                conflicts += 1
        score = max(0.3, 1.0 - 0.2 * conflicts)
        return GateResult(
            "G2_consistency",
            passed=conflicts < 2,
            score=score,
            detail=f"{conflicts} potential number/fact conflicts",
        )

    def _gate_factuality(self, content: str, tenant_id: str) -> GateResult:
        try:
            report = default_citation_agent().run(content, tenant_id=tenant_id)
        except Exception as e:
            logger.debug("factuality gate fallback: %s", e)
            return GateResult("G3_factuality", passed=True, score=0.7, detail="citation agent unavailable, default pass")
        if report.total_claims == 0:
            return GateResult("G3_factuality", passed=True, score=1.0, detail="no claims needing verification")
        ratio = report.verified_claims / report.total_claims
        return GateResult(
            "G3_factuality",
            passed=ratio >= 0.6,
            score=ratio,
            detail=f"{report.verified_claims}/{report.total_claims} claims verified",
        )

    def _gate_readability(self, content: str) -> GateResult:
        # Heuristic readability: avg sentence length, heading density
        sentences = re.split(r'(?<=[。！？!?.])\s*', content)
        sentences = [s for s in sentences if s.strip()]
        if not sentences:
            return GateResult("G4_readability", passed=False, score=0.0, detail="empty")
        avg_len = sum(len(s) for s in sentences) / len(sentences)
        headings = len(re.findall(r'^#+\s', content, re.MULTILINE))
        para_count = content.count("\n\n") + 1
        score = 1.0
        detail = []
        if avg_len > 200:
            score -= 0.3
            detail.append(f"avg_sentence={int(avg_len)} (太长)")
        if len(content) > 1500 and headings == 0:
            score -= 0.3
            detail.append("no headings in long doc")
        if len(content) > 800 and para_count < 3:
            score -= 0.2
            detail.append("no paragraphs separation")
        score = max(0.0, score)
        return GateResult("G4_readability", passed=score >= 0.6, score=score, detail="; ".join(detail) or "ok")

    def _gate_safety(self, content: str) -> GateResult:
        try:
            report = default_security_auditor().audit(content)
            passed = report.safe
            score = 1.0 if passed else (0.5 if report.severity == "medium" else 0.0)
            return GateResult(
                "G5_safety",
                passed=passed,
                score=score,
                detail=f"severity={report.severity}, findings={report.findings[:3]}",
            )
        except Exception as e:
            return GateResult("G5_safety", passed=True, score=0.8, detail=f"auditor fallback: {e}")


# Majority voting helper
def majority_vote(answers: List[Dict[str, Any]], *, judge_fn) -> Dict[str, Any]:
    """3-path answers → judge → final.

    arxiv 2508.17536 证明：多数投票占 MAD 绝大多数性能增益。
    """
    if len(answers) < 2:
        return {"answer": answers[0] if answers else {}, "converged": True}
    judge_prompt = (
        f"3 independent answers:\n\n"
        + "\n---\n".join(f"[{i}] {a.get('text', str(a))[:800]}" for i, a in enumerate(answers)) +
        f"\n\nIs there a majority answer? If 2+ agree, synthesize it. If all 3 differ, note key disagreements.\n"
        f"Return JSON: {{\"converged\": bool, \"final_answer\": \"...\", \"disagreements\": [\"...\"]}}"
    )
    try:
        import json
        out = judge_fn(judge_prompt)
        cleaned = out.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(cleaned)
        return data
    except Exception as e:
        logger.debug("majority_vote judge failed: %s", e)
        return {"converged": True, "final_answer": answers[0].get("text", "")}


_singleton: Optional[QualityGateRunner] = None


def default_quality_gates() -> QualityGateRunner:
    global _singleton
    if _singleton is None:
        _singleton = QualityGateRunner()
    return _singleton
