"""MultiAgentPipeline · 接通 5 named agents 到 Pilot 主流程.

PRD §16 demo 主流程要求展示「Agent 是主驾驶」+ 多 agent 协同。本模块在
``OrchestratorService`` 完成 tool 执行后接管，把生成的 artifact 送进
**Builder-Validator** 链路：

    @pilot ── 编排（已在 OrchestratorService 完成 tool）
       │
       ├── @researcher  ── 上下文召回（已在 ContextService.recall_history）
       │
       ├── @debater     ── 仅 reasoning_pattern == "debate" 时启用
       │                  （正反双方独立 context，3 轮收敛）
       │
       ├── @validator   ── 独立 transcript：5 Quality Gates
       │
       ├── @citation    ── 独立 transcript：每条 claim 标 source
       │
       ├── @mentor      ── 风格 / 受众适配（NVC + 老板汇报场景）
       │
       └── @shield      ── 最终安全审查（PRD §6.1 + 8 层栈兜底）

每个 sub-agent 通过 ``run_subagent`` 隔离 transcript（参考 Claude Code
Sub-agent 设计），父 context 不被污染。

实现策略：
- 不重写 validators/ 与 named_agents/，本模块仅协同
- LLM 调用通过依赖注入（``llm_chat``），测试用 mock
- 任一 sub-agent 失败 → 记录 + 降级（不阻断主流程）
- 全程发布 Domain Event，Dashboard P10 SSE 实时可视化
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..domain import (
    Artifact,
    ArtifactKind,
    EventBus,
    Task,
    default_event_bus,
)
from ..domain.events import make_event

logger = logging.getLogger("pilot.application.multi_agent_pipeline")


# ── 类型注入 ────────────────────────────────────────────────────────────────


# LLMChat 接收一个 messages 列表 + 系统提示，返回字符串
LLMChat = Callable[[List[Dict[str, str]]], str]


# ── 子 agent 角色 ───────────────────────────────────────────────────────────


@dataclass
class AgentTranscript:
    """子 agent 的隔离会话片段."""

    agent: str               # @validator / @citation / @mentor / ...
    role: str                # builder / reviewer / fact-checker / safety / ...
    system_prompt: str = ""
    messages: List[Dict[str, str]] = field(default_factory=list)
    summary: str = ""        # 回传给父 context 的精简结论
    raw_response: str = ""
    duration_ms: int = 0
    ok: bool = True
    error: str = ""


@dataclass
class AgentReport:
    """所有子 agent 的协同报告."""

    pipeline_id: str
    task_id: str
    artifacts_in: List[Artifact] = field(default_factory=list)
    transcripts: List[AgentTranscript] = field(default_factory=list)
    quality_score: float = 0.0
    quality_gates_passed: int = 0
    quality_gates_total: int = 0
    citations_total: int = 0
    citations_verified: int = 0
    safety_blocked: bool = False
    style_revisions: List[str] = field(default_factory=list)
    delivered: bool = False

    @property
    def overall_ok(self) -> bool:
        return (not self.safety_blocked
                and (self.quality_gates_total == 0
                     or self.quality_gates_passed >= self.quality_gates_total - 1))


# ── 主 pipeline ────────────────────────────────────────────────────────────


class MultiAgentPipeline:
    """5 named agents 协同 Builder-Validator-Citation-Mentor-Shield."""

    def __init__(
        self,
        *,
        llm_chat: Optional[LLMChat] = None,
        quality_runner=None,
        citation_agent=None,
        named_agents=None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.llm_chat = llm_chat
        self.quality_runner = quality_runner
        self.citation_agent = citation_agent
        self.named_agents = named_agents
        self.bus = event_bus or default_event_bus()

    # ── 主入口 ─────────────────────────────────────────────────────────────
    def run(self, task: Task, *, content: str = "",
            artifacts: Optional[List[Artifact]] = None) -> AgentReport:
        """对生成的 artifact 跑完整 5-agent 协同。

        ``content`` 是要审查的文本（典型来源：doc.create / slide.generate 的输出）。
        """
        report = AgentReport(
            pipeline_id=f"mp-{int(time.time() * 1000)}",
            task_id=task.task_id,
            artifacts_in=list(artifacts or []),
        )
        self.bus.publish(make_event(
            "multi_agent_started", task.task_id,
            data={"pipeline_id": report.pipeline_id,
                  "reasoning_pattern": (task.plan.reasoning_pattern if task.plan else "")},
        ))

        # 1. @debater (optional, only when pattern == "debate")
        if task.plan and task.plan.reasoning_pattern == "debate":
            self._run_debater(task, content, report)

        # 2. @validator (Builder-Validator separation)
        self._run_validator(task, content, report)

        # 3. @citation (claim → source)
        self._run_citation(task, content, report)

        # 4. @mentor (style / audience adaptation)
        self._run_mentor(task, content, report)

        # 5. @shield (final safety review)
        self._run_shield(task, content, report)

        self.bus.publish(make_event(
            "multi_agent_done", task.task_id,
            data={"pipeline_id": report.pipeline_id,
                  "quality_score": report.quality_score,
                  "gates_passed": report.quality_gates_passed,
                  "citations_verified": report.citations_verified,
                  "safety_blocked": report.safety_blocked,
                  "overall_ok": report.overall_ok},
        ))
        task.log(agent="@pilot", kind="thought",
                  content=f"multi-agent pipeline done: {report.pipeline_id} "
                          f"(quality={report.quality_score:.2f}, "
                          f"gates={report.quality_gates_passed}/"
                          f"{report.quality_gates_total}, "
                          f"safety={'BLOCKED' if report.safety_blocked else 'OK'})")
        return report

    # ── 子 agent 实现 ──────────────────────────────────────────────────────
    def _run_debater(self, task: Task, content: str, report: AgentReport) -> None:
        ts = AgentTranscript(agent="@debater", role="debate-pro-con",
                              system_prompt="你将作为正反两方独立辩论 3 轮，最后给出收敛方案。")
        t0 = time.time()
        if self.llm_chat:
            try:
                ts.raw_response = self.llm_chat([
                    {"role": "system", "content": ts.system_prompt},
                    {"role": "user", "content": (task.intent or "") + "\n\n内容:\n" + content[:2000]},
                ])
            except Exception as e:
                ts.ok = False
                ts.error = str(e)[:200]
                logger.debug("debater llm failed: %s", e)
        ts.duration_ms = int((time.time() - t0) * 1000)
        ts.summary = (ts.raw_response or "").strip()[:300] if ts.ok else f"degraded: {ts.error}"
        report.transcripts.append(ts)
        task.log(agent="@debater", kind="result", content=ts.summary[:200])

    def _run_validator(self, task: Task, content: str, report: AgentReport) -> None:
        ts = AgentTranscript(agent="@validator", role="reviewer",
                              system_prompt="你是独立审查者，不参与生成。"
                                            "运行 5 Quality Gates: Completeness/Consistency/"
                                            "Factuality/Readability/Safety。")
        t0 = time.time()
        if self.quality_runner is not None:
            try:
                qrep = self.quality_runner.run(
                    content,
                    required_fields=None,
                    tenant_id=task.tenant_id,
                )
                # qrep 是 QualityReport（参考 agent/validators/quality_gates.py）
                gates = getattr(qrep, "gates", [])
                report.quality_gates_total = len(gates)
                report.quality_gates_passed = sum(1 for g in gates if getattr(g, "passed", False))
                report.quality_score = float(getattr(qrep, "overall_score", 0.0))
                ts.summary = (
                    f"5 gates: {report.quality_gates_passed}/{report.quality_gates_total} "
                    f"passed, overall={report.quality_score:.2f}"
                )
            except Exception as e:
                ts.ok = False
                ts.error = str(e)[:200]
                logger.warning("quality runner failed: %s", e)
        else:
            # 降级：基础长度/字段检查
            length_ok = len(content) > 100
            report.quality_gates_total = 1
            report.quality_gates_passed = 1 if length_ok else 0
            report.quality_score = 0.6 if length_ok else 0.0
            ts.summary = f"degraded: length_ok={length_ok}"
        ts.duration_ms = int((time.time() - t0) * 1000)
        report.transcripts.append(ts)
        task.log(agent="@validator", kind="result", content=ts.summary[:200])

    def _run_citation(self, task: Task, content: str, report: AgentReport) -> None:
        ts = AgentTranscript(agent="@citation", role="fact-checker",
                              system_prompt="你独立给每条 claim 标 source，不做生成。")
        t0 = time.time()
        if self.citation_agent is not None:
            try:
                claims = self.citation_agent.extract_claims(content) or []
                report.citations_total = len(claims)
                # 简化：本模块不做真实 source 查询，由 citation_agent.verify 完成
                if hasattr(self.citation_agent, "verify_all"):
                    try:
                        verified = self.citation_agent.verify_all(claims) or []
                        report.citations_verified = sum(1 for c in verified if getattr(c, "verified", False))
                    except Exception:
                        report.citations_verified = 0
                ts.summary = f"{report.citations_total} claims, {report.citations_verified} verified"
            except Exception as e:
                ts.ok = False
                ts.error = str(e)[:200]
                logger.debug("citation agent failed: %s", e)
        else:
            ts.summary = "citation agent not configured"
        ts.duration_ms = int((time.time() - t0) * 1000)
        report.transcripts.append(ts)
        task.log(agent="@citation", kind="result", content=ts.summary[:200])

    def _run_mentor(self, task: Task, content: str, report: AgentReport) -> None:
        """@mentor 风格审查：根据 ContextPack.output_requirements.style 给修订建议."""
        ts = AgentTranscript(agent="@mentor", role="style-coach")
        t0 = time.time()
        cp = task.context_pack
        target = ""
        if cp:
            target = cp.output_requirements.audience or cp.output_requirements.style or ""
        if self.llm_chat and target:
            try:
                ts.system_prompt = (
                    f"你是表达带教 @mentor。根据『{target}』的语境，对内容做风格修订建议。"
                    "只给 ≤3 条修订要点，不重写正文。"
                )
                ts.raw_response = self.llm_chat([
                    {"role": "system", "content": ts.system_prompt},
                    {"role": "user", "content": content[:2000]},
                ])
                ts.summary = ts.raw_response.strip()[:200]
                report.style_revisions = [
                    line.strip() for line in ts.raw_response.splitlines()
                    if line.strip() and (line.strip().startswith(("-", "•", "1", "2", "3")))
                ][:3]
            except Exception as e:
                ts.ok = False
                ts.error = str(e)[:200]
        else:
            ts.summary = "mentor pass (no audience/style hint)"
        ts.duration_ms = int((time.time() - t0) * 1000)
        report.transcripts.append(ts)
        task.log(agent="@mentor", kind="result", content=ts.summary[:200])

    def _run_shield(self, task: Task, content: str, report: AgentReport) -> None:
        """@shield 最终安全审查：基础 PII / 敏感词扫描。"""
        ts = AgentTranscript(agent="@shield", role="safety-auditor")
        t0 = time.time()
        # 基础脱敏检查（更严的扫描在 8 层安全栈里已做）
        red_flags: List[str] = []
        for pat, label in [
            (r"\b1[3-9]\d{9}\b", "phone"),
            (r"\b\d{15,18}\b", "id-card-like"),
            (r"App ?Secret[:=]\s*\S+", "secret"),
            (r"sk-[A-Za-z0-9_-]{12,}", "api-key"),
        ]:
            import re
            if re.search(pat, content):
                red_flags.append(label)
        report.safety_blocked = bool(red_flags)
        ts.summary = ("BLOCKED: " + ", ".join(red_flags)) if red_flags else "OK"
        ts.duration_ms = int((time.time() - t0) * 1000)
        report.transcripts.append(ts)
        task.log(agent="@shield", kind="result", content=ts.summary[:200])


__all__ = [
    "MultiAgentPipeline",
    "AgentTranscript",
    "AgentReport",
]
