"""4-Agent 协作工坊 – v13 创新点 #1.

The four agents work as a small assembly line so that each piece of work has
a clear single responsibility (instead of the monolithic "one prompt does it
all" approach). They run mostly serially but share a common ContextPack so
later agents can audit earlier outputs.

Pipeline:
    Researcher → Writer → Critic → Presenter
        |           |        |          |
        |           |        |          → outline JSON for slide.generate
        |           |        |          → canvas spec JSON for canvas.create
        |           |        +→ rejects writer once if score < 70
        |           +→ markdown 文档（同时是 Presenter 的输入）
        +→ 资料包 JSON

The pipeline is exposed as a single ``run_workforce(intent, context)`` call
that returns a ``WorkforceResult`` with intermediate states preserved so the
Dashboard can visualize each agent's "thinking".
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent_pilot.llm.safe_json import safe_json_parse

logger = logging.getLogger("agent_pilot.intel.multi_agent")


# ── Shared context model ──────────────────────────────────────────────────────


@dataclass
class AgentTrace:
    name: str
    started_ts: float
    finished_ts: float = 0.0
    duration_sec: float = 0.0
    input_summary: str = ""
    output_summary: str = ""
    score: Optional[float] = None
    notes: str = ""
    raw_output: str = ""


@dataclass
class WorkforceResult:
    intent: str
    research: Dict[str, Any] = field(default_factory=dict)
    document_md: str = ""
    critique: Dict[str, Any] = field(default_factory=dict)
    slide_outline: List[Dict[str, Any]] = field(default_factory=list)
    canvas_spec: Dict[str, Any] = field(default_factory=dict)
    traces: List[AgentTrace] = field(default_factory=list)
    iterations: int = 0


# ── Helpers ───────────────────────────────────────────────────────────────────


def _llm_chat(prompt: str, *, system: str = "", temperature: float = 0.5,
              max_tokens: int = 8192) -> str:
    """Thin wrapper so we can swap the provider without touching agents."""
    try:
        from llm.llm_client import chat as _chat
        return _chat(prompt, temperature=temperature, max_tokens=max_tokens, system=system)
    except Exception as e:
        logger.error("multi_agent llm call failed: %s", e)
        return ""


def _summarise(text: str, n: int = 120) -> str:
    if not text:
        return ""
    one_line = " ".join(text.split())
    return one_line[:n] + ("…" if len(one_line) > n else "")


# ── Agent 1: Researcher ───────────────────────────────────────────────────────


_RESEARCHER_SYSTEM = (
    "你是 Agent-Pilot 工坊里的资料调研员（Researcher）。"
    "你的职责是把用户意图与可见上下文整理成一份结构化资料包，"
    "为后续的写作 Agent 提供输入。你只输出 JSON。"
)


def _run_researcher(intent: str, thread_context: str) -> tuple[Dict[str, Any], AgentTrace]:
    t0 = time.time()
    trace = AgentTrace(name="Researcher", started_ts=t0,
                       input_summary=_summarise(intent + " | " + thread_context))
    prompt = f"""请基于以下信息整理资料包：

## 用户意图
{intent}

## 群聊/对话上下文（可能为空）
{thread_context or '（无）'}

请输出严格 JSON：
{{
  "topic": "任务主题",
  "key_questions": ["核心问题1", "核心问题2", "核心问题3"],
  "key_facts": ["可信事实1（含数据）", "可信事实2"],
  "stakeholders": ["利益相关方1", "..."],
  "risks": ["潜在风险1"],
  "outline_hint": ["建议章节1", "建议章节2", "..."]
}}

要求：内容必须紧扣用户意图，不要凭空发挥；如上下文为空，用领域常识补全。直接输出 JSON。"""
    raw = _llm_chat(prompt, system=_RESEARCHER_SYSTEM, temperature=0.3, max_tokens=4096)
    obj = safe_json_parse(raw, expected_type=dict, debug_label="researcher")
    trace.raw_output = raw[:2000]
    trace.finished_ts = time.time()
    trace.duration_sec = trace.finished_ts - t0
    if obj:
        trace.output_summary = _summarise(
            f"主题={obj.get('topic')}，问题{len(obj.get('key_questions', []))}，"
            f"事实{len(obj.get('key_facts', []))}，章节{len(obj.get('outline_hint', []))}"
        )
        trace.notes = "ok"
    else:
        trace.output_summary = "（解析失败，将由 Writer 直接处理 intent）"
        trace.notes = "json_parse_failed"
        obj = {
            "topic": intent[:50],
            "key_questions": [],
            "key_facts": [],
            "stakeholders": [],
            "risks": [],
            "outline_hint": [],
        }
    return obj, trace


# ── Agent 2: Writer ───────────────────────────────────────────────────────────


_WRITER_SYSTEM = (
    "你是 Agent-Pilot 工坊里的资深写作员（Writer）。"
    "你的职责是把 Researcher 的资料包扩写成一份完整、专业、详尽的 Markdown 文档。"
    "你不输出元信息，只输出文档正文 markdown。"
)


def _run_writer(intent: str, research: Dict[str, Any],
                feedback: str = "") -> tuple[str, AgentTrace]:
    t0 = time.time()
    trace = AgentTrace(name="Writer", started_ts=t0,
                       input_summary=_summarise(json.dumps(research, ensure_ascii=False)))
    research_text = json.dumps(research, ensure_ascii=False, indent=2)
    prompt = f"""请把以下资料包扩写成一份完整的 Markdown 文档。

## 用户原始意图
{intent}

## 资料包
{research_text}

{"## Critic 反馈（请重点改进）" + chr(10) + feedback if feedback else ""}

## 文档结构要求
- 用 ## 作为章节大标题，### 作为子标题，- 作为列表项
- 章节包含：概述、背景、核心分析（2-3 章）、案例、风险、结论
- 每个章节 3-5 段充实内容，有数据、有案例、有论据
- 总字数 1500+ 字
- 直接从 ## 开始输出，不要前言"""
    raw = _llm_chat(prompt, system=_WRITER_SYSTEM, temperature=0.5, max_tokens=16384)
    raw = (raw or "").strip()
    if raw.startswith("```"):
        # strip wrapping fences
        import re as _re
        m = _re.search(r"```(?:markdown)?\s*([\s\S]+?)```", raw)
        if m:
            raw = m.group(1).strip()
    trace.finished_ts = time.time()
    trace.duration_sec = trace.finished_ts - t0
    trace.raw_output = raw[:2000]
    trace.output_summary = f"{len(raw)} 字符 / {raw.count(chr(10) + '## ')} 章节"
    trace.notes = "ok" if len(raw) >= 600 else "short"
    return raw, trace


# ── Agent 3: Critic ───────────────────────────────────────────────────────────


_CRITIC_SYSTEM = (
    "你是 Agent-Pilot 工坊里的严格评审员（Critic）。"
    "你的职责是对 Writer 输出的文档做 5 维度评分（结构/数据/逻辑/可读性/合规），"
    "并指出具体不足。你只输出 JSON。"
)


def _run_critic(document_md: str) -> tuple[Dict[str, Any], AgentTrace]:
    t0 = time.time()
    trace = AgentTrace(name="Critic", started_ts=t0,
                       input_summary=f"document {len(document_md)} chars")
    preview = document_md[:8000]
    prompt = f"""请对下面的文档做严格评审：

{preview}

请输出严格 JSON：
{{
  "scores": {{
    "structure": 0-100,    // 章节组织、层级
    "data": 0-100,         // 数据/案例/事实支撑
    "logic": 0-100,        // 论证逻辑、因果关系
    "readability": 0-100,  // 语言流畅、可读性
    "compliance": 0-100    // 是否切题、合规
  }},
  "overall": 0-100,        // 5 维度加权后总分
  "issues": ["具体问题1", "具体问题2"],
  "improvement_hints": ["改进建议1", "改进建议2"]
}}

只输出 JSON。"""
    raw = _llm_chat(prompt, system=_CRITIC_SYSTEM, temperature=0.2, max_tokens=2048)
    obj = safe_json_parse(raw, expected_type=dict, debug_label="critic")
    trace.raw_output = raw[:2000]
    trace.finished_ts = time.time()
    trace.duration_sec = trace.finished_ts - t0
    if obj and "overall" in obj:
        trace.score = float(obj.get("overall", 0))
        trace.output_summary = f"overall={trace.score:.0f}, issues={len(obj.get('issues', []))}"
        trace.notes = "ok"
    else:
        # If parsing fails, default to a passing-ish score so we don't loop forever
        trace.score = 75.0
        obj = {
            "scores": {"structure": 75, "data": 75, "logic": 75, "readability": 75, "compliance": 75},
            "overall": 75,
            "issues": [],
            "improvement_hints": [],
        }
        trace.output_summary = "(critic json parse failed, defaulting to 75)"
        trace.notes = "json_parse_failed_default_75"
    return obj, trace


# ── Agent 4a: Presenter – Slide Outline ──────────────────────────────────────

_PRESENTER_SLIDES_SYSTEM = (
    "你是 Agent-Pilot 工坊里的演示设计师（Presenter）。"
    "你的职责是把已通过 Critic 的文档转化为 8-12 页高质量 PPT 大纲。"
    "你只输出 JSON 数组，不输出其他任何内容。"
)


def _run_presenter_slides(
    intent: str, document_md: str, *, max_retries: int = 2
) -> tuple[List[Dict[str, Any]], AgentTrace]:
    """独立调用：只生成 slide_outline JSON 数组，最多重试 max_retries 次。"""
    t0 = time.time()
    trace = AgentTrace(
        name="Presenter-Slides",
        started_ts=t0,
        input_summary=f"document {len(document_md)} chars",
    )
    # 截取文档前 12000 字给 LLM，留出足够 output token
    preview = document_md[:12000]

    def _build_prompt(short: bool = False) -> str:
        doc_text = document_md[:6000] if short else preview
        return f"""基于以下文档，为主题「{intent[:60]}」设计一份 8-12 页的 PPT 大纲。

## 文档内容（节选）
{doc_text}

请输出 JSON 数组，每个元素包含 title、bullets（3-5 条完整句子）、note（演讲稿 80-120 字）：
[
  {{"title": "封面", "bullets": ["副标题（一句话价值主张）", "演讲者"], "note": "开场介绍"}},
  {{"title": "目录", "bullets": ["章节1", "章节2", "章节3"], "note": "今天要讲的内容"}},
  ...
]

要求：8-12 页；内容与文档保持一致；包含封面、目录、3-5页核心内容、案例、结论、Thank You。
直接输出 JSON 数组，不要 markdown 代码块，不要任何前缀。"""

    slide_outline: List[Dict[str, Any]] = []
    for attempt in range(max_retries + 1):
        temperature = 0.4 + attempt * 0.15  # 重试时略微升温
        short_prompt = attempt >= 1          # 第二次起用更短的文档
        raw = _llm_chat(
            _build_prompt(short=short_prompt),
            system=_PRESENTER_SLIDES_SYSTEM,
            temperature=temperature,
            max_tokens=6000,
        )
        obj = safe_json_parse(raw, expected_type=list, debug_label=f"presenter-slides-attempt{attempt}")
        if obj and len(obj) >= 4:
            slide_outline = [
                {
                    "title": str(p.get("title") or f"Slide {i}").strip(),
                    "bullets": [str(b).strip() for b in (p.get("bullets") or []) if str(b).strip()],
                    "note": str(p.get("note") or "").strip(),
                }
                for i, p in enumerate(obj, 1)
                if isinstance(p, dict)
            ]
            trace.notes = f"ok (attempt {attempt})"
            logger.info("presenter-slides: got %d pages on attempt %d", len(slide_outline), attempt)
            break
        logger.warning(
            "presenter-slides attempt %d/%d: parsed %d pages, retrying…",
            attempt, max_retries, len(obj) if obj else 0,
        )

    trace.finished_ts = time.time()
    trace.duration_sec = trace.finished_ts - t0
    trace.output_summary = f"slides={len(slide_outline)}"
    if not slide_outline:
        trace.notes = f"failed after {max_retries + 1} attempts"
    return slide_outline, trace


# ── Agent 4b: Presenter – Canvas Spec ────────────────────────────────────────

_PRESENTER_CANVAS_SYSTEM = (
    "你是 Agent-Pilot 工坊里的架构图设计师（Presenter-Canvas）。"
    "你的职责是把文档转化为 5-10 节点的架构/流程图 spec JSON。"
    "你只输出 JSON 对象，不输出其他任何内容。"
)


def _run_presenter_canvas(
    intent: str, document_md: str, *, max_retries: int = 2
) -> tuple[Dict[str, Any], AgentTrace]:
    """独立调用：只生成 canvas_spec JSON 对象，最多重试 max_retries 次。"""
    t0 = time.time()
    trace = AgentTrace(
        name="Presenter-Canvas",
        started_ts=t0,
        input_summary=f"document {len(document_md)} chars",
    )
    preview = document_md[:8000]

    def _build_prompt(short: bool = False) -> str:
        doc_text = document_md[:4000] if short else preview
        return f"""基于以下文档，为主题「{intent[:60]}」设计一张架构/流程图。

## 文档内容（节选）
{doc_text}

请输出 JSON 对象：
{{
  "title": "图的标题",
  "layout": "tb",
  "nodes": [
    {{"id": "n1", "label": "节点名称", "type": "input", "tier": 1}},
    {{"id": "n2", "label": "节点名称", "type": "process", "tier": 2}},
    ...共 5-10 个节点
  ],
  "edges": [
    {{"from": "n1", "to": "n2", "label": "关系描述"}},
    ...共 4-12 条边
  ]
}}

节点 type 可选：input / process / store / output / decision
直接输出 JSON 对象，不要 markdown 代码块，不要任何前缀。"""

    canvas_spec: Dict[str, Any] = {}
    for attempt in range(max_retries + 1):
        temperature = 0.3 + attempt * 0.1
        short_prompt = attempt >= 1
        raw = _llm_chat(
            _build_prompt(short=short_prompt),
            system=_PRESENTER_CANVAS_SYSTEM,
            temperature=temperature,
            max_tokens=3000,
        )
        obj = safe_json_parse(raw, expected_type=dict, debug_label=f"presenter-canvas-attempt{attempt}")
        if obj and obj.get("nodes") and len(obj["nodes"]) >= 3:
            canvas_spec = obj
            trace.notes = f"ok (attempt {attempt})"
            logger.info("presenter-canvas: got %d nodes on attempt %d",
                        len(obj["nodes"]), attempt)
            break
        logger.warning(
            "presenter-canvas attempt %d/%d: nodes=%d, retrying…",
            attempt, max_retries,
            len(obj.get("nodes", [])) if isinstance(obj, dict) else 0,
        )

    trace.finished_ts = time.time()
    trace.duration_sec = trace.finished_ts - t0
    trace.output_summary = f"canvas_nodes={len(canvas_spec.get('nodes', []))}"
    if not canvas_spec:
        trace.notes = f"failed after {max_retries + 1} attempts"
    return canvas_spec, trace


# ── Public entry point ────────────────────────────────────────────────────────


def run_workforce(
    intent: str,
    *,
    thread_context: str = "",
    enable_critic: bool = True,
    critic_threshold: float = 70.0,
    plan_id: str = "",
) -> WorkforceResult:
    """Run the 4-Agent assembly line."""
    result = WorkforceResult(intent=intent)

    research, t1 = _run_researcher(intent, thread_context)
    result.research = research
    result.traces.append(t1)
    _persist_trace(plan_id, t1)

    document_md, t2 = _run_writer(intent, research)
    result.traces.append(t2)
    _persist_trace(plan_id, t2)

    critique: Dict[str, Any] = {}
    if enable_critic:
        critique, t3 = _run_critic(document_md)
        result.traces.append(t3)
        _persist_trace(plan_id, t3)
        result.iterations = 1
        if t3.score is not None and t3.score < critic_threshold:
            # one-shot retry with feedback
            feedback = "\n".join(critique.get("improvement_hints", []))
            document_md_v2, t2b = _run_writer(intent, research, feedback=feedback)
            result.traces.append(t2b)
            _persist_trace(plan_id, t2b)
            if len(document_md_v2) >= len(document_md) * 0.7:
                document_md = document_md_v2
            result.iterations = 2

    result.document_md = document_md
    result.critique = critique

    # 4a: Slide outline（独立调用，独立重试）
    slide_outline, t4a = _run_presenter_slides(intent, document_md, max_retries=2)
    result.slide_outline = slide_outline
    result.traces.append(t4a)
    _persist_trace(plan_id, t4a)

    # 4b: Canvas spec（独立调用，独立重试）
    canvas_spec, t4b = _run_presenter_canvas(intent, document_md, max_retries=2)
    result.canvas_spec = canvas_spec
    result.traces.append(t4b)
    _persist_trace(plan_id, t4b)

    # 任一失败则记录警告（调用方可据此通知用户）
    if not slide_outline:
        logger.warning("run_workforce: slide_outline empty after retries for plan_id=%s", plan_id)
    if not canvas_spec:
        logger.warning("run_workforce: canvas_spec empty after retries for plan_id=%s", plan_id)

    return result


def _persist_trace(plan_id: str, trace: AgentTrace) -> None:
    """Append a trace to ``data/agent_traces/{plan_id}.jsonl`` for Dashboard."""
    if not plan_id:
        return
    try:
        from pathlib import Path
        d = Path(__file__).resolve().parent.parent.parent / "data" / "agent_traces"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{plan_id}.jsonl"
        line = json.dumps({
            "name": trace.name,
            "started_ts": trace.started_ts,
            "finished_ts": trace.finished_ts,
            "duration_sec": trace.duration_sec,
            "input_summary": trace.input_summary,
            "output_summary": trace.output_summary,
            "score": trace.score,
            "notes": trace.notes,
        }, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        logger.debug("trace persist failed: %s", e)


__all__ = ["WorkforceResult", "AgentTrace", "run_workforce"]
