"""P6 · MultiAgentPipeline 测试 (Builder-Validator + 5 named agents)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

from core.agent_pilot.application import (
    AgentReport,
    AgentTranscript,
    ContextBuildOptions,
    ContextService,
    MultiAgentPipeline,
    PlannerService,
    TaskService,
)
from core.agent_pilot.application.task_service import TaskRepository
from core.agent_pilot.domain import Artifact, ArtifactKind


# ── Mock Quality Runner ─────────────────────────────────────────────────────


@dataclass
class MockGate:
    name: str
    passed: bool
    score: float
    detail: str = ""


@dataclass
class MockQualityReport:
    gates: List[MockGate]
    overall_passed: bool
    overall_score: float


class MockQualityRunner:
    def __init__(self, *, all_pass: bool = True, score: float = 0.85):
        self.all_pass = all_pass
        self.score = score

    def run(self, content: str, **kwargs):
        gates = [
            MockGate("completeness", self.all_pass, 0.9),
            MockGate("consistency", self.all_pass, 0.85),
            MockGate("factuality", self.all_pass, 0.8),
            MockGate("readability", self.all_pass, 0.9),
            MockGate("safety", self.all_pass, 0.95),
        ]
        return MockQualityReport(
            gates=gates,
            overall_passed=self.all_pass,
            overall_score=self.score,
        )


# ── Mock Citation Agent ─────────────────────────────────────────────────────


@dataclass
class MockClaim:
    text: str
    kind: str
    verified: bool = False


class MockCitationAgent:
    def __init__(self, *, claims_count: int = 4, verified_count: int = 3):
        self.claims_count = claims_count
        self.verified_count = verified_count

    def extract_claims(self, text: str):
        return [MockClaim(text=f"claim {i}", kind="data") for i in range(self.claims_count)]

    def verify_all(self, claims):
        out = []
        for i, c in enumerate(claims):
            c.verified = i < self.verified_count
            out.append(c)
        return out


# ── Mock LLM ────────────────────────────────────────────────────────────────


def _mock_llm_simple(messages):
    return "- 修订要点1\n- 修订要点2\n- 修订要点3"


# ── Fixture: task with plan ─────────────────────────────────────────────────


@pytest.fixture
def task_ready_for_pipeline(tmp_path):
    svc = TaskService(repository=TaskRepository(root=str(tmp_path)))
    ctx_svc = ContextService(upload_root=str(tmp_path))

    def make(intent: str = "活动复盘汇报", primary: str = "ppt",
             audience: str = "leader", reasoning_pattern: str = "cot"):
        t = svc.create_task(intent=intent, owner_open_id="u1")
        cp = ctx_svc.build(ContextBuildOptions(
            task_id=t.task_id, task_goal=intent, owner_open_id="u1",
            output_primary=primary, output_audience=audience,
        ))
        t.attach_context(cp, confirmed=True)
        ps = PlannerService(planner_factory=False)
        ps.plan_for_task(t)
        if reasoning_pattern:
            t.plan.reasoning_pattern = reasoning_pattern
        return t

    return make


# ── Tests ───────────────────────────────────────────────────────────────────


def test_pipeline_runs_full_chain(task_ready_for_pipeline):
    t = task_ready_for_pipeline()
    pipe = MultiAgentPipeline(
        llm_chat=_mock_llm_simple,
        quality_runner=MockQualityRunner(all_pass=True, score=0.92),
        citation_agent=MockCitationAgent(),
    )
    content = "本次校园推广活动覆盖 2400 人。根据 2025 年数据，参与率上升 15%。"
    rep = pipe.run(t, content=content, artifacts=[
        Artifact(artifact_id="a1", task_id="", kind=ArtifactKind.DOC, title="复盘"),
    ])
    assert rep.task_id == t.task_id
    assert rep.quality_gates_total == 5
    assert rep.quality_gates_passed == 5
    assert rep.quality_score == 0.92
    assert rep.citations_total == 4
    assert rep.citations_verified == 3
    assert not rep.safety_blocked
    assert rep.overall_ok
    # 至少 4 个子 agent transcript（cot 模式不跑 debater）
    assert len(rep.transcripts) >= 4


def test_pipeline_runs_debater_for_debate_pattern(task_ready_for_pipeline):
    t = task_ready_for_pipeline(reasoning_pattern="debate")
    pipe = MultiAgentPipeline(
        llm_chat=_mock_llm_simple,
        quality_runner=MockQualityRunner(),
        citation_agent=MockCitationAgent(),
    )
    rep = pipe.run(t, content="content")
    agents = [ts.agent for ts in rep.transcripts]
    assert "@debater" in agents


def test_pipeline_skips_debater_for_cot(task_ready_for_pipeline):
    t = task_ready_for_pipeline(reasoning_pattern="cot")
    pipe = MultiAgentPipeline(
        llm_chat=_mock_llm_simple,
        quality_runner=MockQualityRunner(),
        citation_agent=MockCitationAgent(),
    )
    rep = pipe.run(t, content="content")
    agents = [ts.agent for ts in rep.transcripts]
    assert "@debater" not in agents


def test_pipeline_safety_blocks_pii(task_ready_for_pipeline):
    t = task_ready_for_pipeline()
    pipe = MultiAgentPipeline(
        llm_chat=_mock_llm_simple,
        quality_runner=MockQualityRunner(),
        citation_agent=MockCitationAgent(),
    )
    bad_content = "联系电话 13912345678，App Secret = abc123ABC456"
    rep = pipe.run(t, content=bad_content)
    assert rep.safety_blocked
    assert not rep.overall_ok
    shield = next(ts for ts in rep.transcripts if ts.agent == "@shield")
    assert "BLOCKED" in shield.summary


def test_pipeline_validator_failure_does_not_break(task_ready_for_pipeline):
    """Quality runner 抛异常 → transcript ok=False，但 pipeline 不挂掉."""
    class BrokenRunner:
        def run(self, *_, **__):
            raise RuntimeError("downstream qg crashed")
    t = task_ready_for_pipeline()
    pipe = MultiAgentPipeline(
        llm_chat=_mock_llm_simple,
        quality_runner=BrokenRunner(),
        citation_agent=MockCitationAgent(),
    )
    rep = pipe.run(t, content="hello world")
    val = next(ts for ts in rep.transcripts if ts.agent == "@validator")
    assert not val.ok
    assert "crashed" in val.error


def test_pipeline_degrades_without_quality_runner(task_ready_for_pipeline):
    t = task_ready_for_pipeline()
    pipe = MultiAgentPipeline(
        llm_chat=_mock_llm_simple,
        quality_runner=None,  # 不注入
        citation_agent=MockCitationAgent(),
    )
    rep = pipe.run(t, content="x" * 200)
    assert rep.quality_gates_total == 1
    assert rep.quality_gates_passed == 1
    val = next(ts for ts in rep.transcripts if ts.agent == "@validator")
    assert "degraded" in val.summary


def test_pipeline_logs_to_task_agent_log(task_ready_for_pipeline):
    t = task_ready_for_pipeline()
    pipe = MultiAgentPipeline(
        llm_chat=_mock_llm_simple,
        quality_runner=MockQualityRunner(),
        citation_agent=MockCitationAgent(),
    )
    pipe.run(t, content="content")
    agents_logged = {l.agent for l in t.agent_logs}
    assert "@validator" in agents_logged
    assert "@citation" in agents_logged
    assert "@mentor" in agents_logged
    assert "@shield" in agents_logged


def test_pipeline_emits_events(task_ready_for_pipeline):
    from core.agent_pilot.domain import EventBus
    bus = EventBus()
    received = []
    bus.subscribe(received.append)
    t = task_ready_for_pipeline()
    pipe = MultiAgentPipeline(
        llm_chat=_mock_llm_simple,
        quality_runner=MockQualityRunner(),
        citation_agent=MockCitationAgent(),
        event_bus=bus,
    )
    pipe.run(t, content="content")
    kinds = {e.event_kind for e in received}
    assert "multi_agent_started" in kinds
    assert "multi_agent_done" in kinds


def test_pipeline_mentor_extracts_revisions(task_ready_for_pipeline):
    t = task_ready_for_pipeline(audience="leader")
    pipe = MultiAgentPipeline(
        llm_chat=_mock_llm_simple,
        quality_runner=MockQualityRunner(),
        citation_agent=MockCitationAgent(),
    )
    rep = pipe.run(t, content="content")
    assert len(rep.style_revisions) == 3


def test_pipeline_overall_ok_when_one_gate_fails(task_ready_for_pipeline):
    """允许 1 个 gate 失败仍 overall_ok（弹性容忍）."""
    class Mostly:
        def run(self, *_, **__):
            gates = [MockGate(f"g{i}", i != 0, 0.8) for i in range(5)]
            return MockQualityReport(gates=gates, overall_passed=False, overall_score=0.7)
    t = task_ready_for_pipeline()
    pipe = MultiAgentPipeline(
        llm_chat=_mock_llm_simple,
        quality_runner=Mostly(),
        citation_agent=MockCitationAgent(),
    )
    rep = pipe.run(t, content="content")
    assert rep.quality_gates_passed == 4
    assert rep.overall_ok  # 1 gate 失败仍允许


def test_pipeline_safety_blocks_overall_ok(task_ready_for_pipeline):
    t = task_ready_for_pipeline()
    pipe = MultiAgentPipeline(
        llm_chat=_mock_llm_simple,
        quality_runner=MockQualityRunner(all_pass=True),
        citation_agent=MockCitationAgent(),
    )
    rep = pipe.run(t, content="leak: sk-AAABBBCCCDDD0000")
    assert rep.safety_blocked
    assert not rep.overall_ok  # safety 一票否决
