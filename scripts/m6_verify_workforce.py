#!/usr/bin/env python3
"""M6 verification: 4-Agent workforce end-to-end with a mocked LLM.

Confirms:
 - Researcher → Writer → Critic → Presenter all run
 - Output dataclass populated with traces
 - Trace persisted to data/agent_traces/{plan_id}.jsonl
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent_pilot.intel.multi_agent as ma  # noqa: E402

# Long, realistic-looking writer output so the document length check passes
WRITER_DOC = """## 概述

人工智能代理（AI Agent）正在从单纯的对话生成器，演化为能够主动理解任务、规划步骤、调用工具的自主智能体。本报告基于行业研究数据与典型案例，系统梳理 AI Agent 的发展现状、技术演进、应用场景与未来挑战。

## 行业现状

根据 Gartner 2024 年报告，全球 AI Agent 市场规模已突破 50 亿美元，预计 2027 年将达到 200 亿美元，复合增长率超过 50%。头部模型公司（OpenAI、Anthropic、Google）已经将 Agent 化作为下一代产品的核心战略。

国内方面，飞书、钉钉、企业微信等 IM 平台开始集成 AI Agent 能力，为团队协作提供智能助手。

## 技术演进

### 从 chat 到 ReAct
早期的 LLM 应用以单轮对话为主。2023 年起，ReAct 范式出现，让模型在思考与行动之间循环。

### 多 Agent 协作
更复杂的任务需要多个 Agent 协作：Builder 负责生成、Critic 负责评审，仲裁机制保证产出质量。

### 工具协议标准化
MCP（Model Context Protocol）让 Agent 可以接入不同的工具与数据源，构建统一的工具生态。

## 应用场景

- 办公协同：从 IM 对话直接生成文档与 PPT
- 代码助手：Cursor/Copilot 重塑研发流程
- 客户服务：7×24 多模态智能客服

## 风险与挑战

幻觉、隐私、合规是三大主要风险。本地化部署、端到端加密、Critic 二次校验是缓解手段。

## 结论与展望

AI Agent 正在从概念验证迈向规模化应用。AI Native 应用将逐步取代以 GUI 为中心的工具堆砌。
"""

RESEARCHER_JSON = """{
  "topic": "AI Agent 发展趋势",
  "key_questions": ["市场规模如何？", "技术路线如何演进？", "落地难点是什么？"],
  "key_facts": ["全球 AI Agent 市场 2024 年突破 50 亿美元", "ReAct 范式 2023 年提出"],
  "stakeholders": ["头部模型公司", "企业用户", "开发者"],
  "risks": ["幻觉传播", "隐私合规"],
  "outline_hint": ["概述", "现状", "技术演进", "应用场景", "风险", "展望"]
}"""

CRITIC_JSON = """{
  "scores": {
    "structure": 80, "data": 75, "logic": 80, "readability": 85, "compliance": 90
  },
  "overall": 82,
  "issues": ["数据来源可以更具体"],
  "improvement_hints": []
}"""

PRESENTER_JSON = """{
  "slide_outline": [
    {"title": "AI Agent 发展趋势", "bullets": ["AI 驱动办公协同", "Agent-Pilot 团队"], "note": "开场"},
    {"title": "目录", "bullets": ["现状", "技术", "应用", "风险"], "note": "讲四部分"},
    {"title": "市场现状", "bullets": ["全球 50 亿美元", "增长率 50%"], "note": "市场数据"},
    {"title": "技术演进", "bullets": ["ReAct", "Multi-Agent", "MCP"], "note": "三大方向"},
    {"title": "应用场景", "bullets": ["办公", "代码", "客服"], "note": "三大场景"},
    {"title": "风险展望", "bullets": ["幻觉", "隐私", "AI Native"], "note": "未来方向"},
    {"title": "Thank You", "bullets": ["GitHub: bcefghj/Agent-Pilot"], "note": "感谢"}
  ],
  "canvas_spec": {
    "title": "AI Agent 生态架构",
    "layout": "tb",
    "nodes": [
      {"id": "user", "label": "终端用户", "type": "input", "tier": 1},
      {"id": "agent", "label": "AI Agent", "type": "process", "tier": 2},
      {"id": "tools", "label": "工具生态(MCP)", "type": "process", "tier": 3},
      {"id": "data", "label": "知识库", "type": "store", "tier": 3},
      {"id": "output", "label": "产物输出", "type": "output", "tier": 4}
    ],
    "edges": [
      {"from": "user", "to": "agent", "label": "意图"},
      {"from": "agent", "to": "tools", "label": "调用"},
      {"from": "agent", "to": "data", "label": "检索"},
      {"from": "tools", "to": "output", "label": "生成"},
      {"from": "data", "to": "output", "label": ""}
    ]
  }
}"""


def mock_llm_chat(prompt: str, *, system: str = "", temperature: float = 0.5,
                  max_tokens: int = 8192) -> str:
    # Match Chinese role names — they're unique per agent.
    if "资料调研员" in system:
        return RESEARCHER_JSON
    if "评审员" in system:
        return CRITIC_JSON
    if "演示设计师" in system:
        return PRESENTER_JSON
    if "写作员" in system:
        return WRITER_DOC
    raise RuntimeError(f"mock_llm_chat: unmatched system prompt: {system[:80]!r}")


def main():
    ma._llm_chat = mock_llm_chat
    plan_id = "test_m6_workforce"

    result = ma.run_workforce(
        intent="AI Agent 发展趋势报告",
        thread_context="",
        enable_critic=True,
        plan_id=plan_id,
    )

    print(f"intent: {result.intent}")
    print(f"research topic: {result.research.get('topic')}")
    print(f"document length: {len(result.document_md)} chars")
    print(f"critique overall: {result.critique.get('overall')}")
    print(f"slide outline pages: {len(result.slide_outline)}")
    print(f"canvas spec nodes: {len(result.canvas_spec.get('nodes', []))}")
    print(f"canvas spec edges: {len(result.canvas_spec.get('edges', []))}")
    print(f"traces ({len(result.traces)}):")
    for t in result.traces:
        print(f"  - {t.name}: {t.duration_sec:.2f}s | {t.output_summary}")
    print(f"iterations: {result.iterations}")

    # Trace file?
    trace_file = ROOT / "data" / "agent_traces" / f"{plan_id}.jsonl"
    if trace_file.exists():
        print(f"trace file: {trace_file} ({trace_file.stat().st_size} bytes)")

    # Assertions
    assert len(result.document_md) > 600, f"doc too short: {len(result.document_md)}"
    assert len(result.slide_outline) >= 4
    assert len(result.canvas_spec.get("nodes", [])) >= 4
    assert len(result.traces) >= 4
    assert result.critique.get("overall", 0) > 70
    print()
    print("✅ M6 workforce verification PASSED")


if __name__ == "__main__":
    main()
