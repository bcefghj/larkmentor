"""Planner — Few-Shot DAG planner（Anthropic Orchestrator-Worker 模式）.

将自然语言意图拆解为 DAG plan。设计上避免依赖 LLM：
  - 优先尝试 LLM JSON 输出
  - 失败回落到启发式规则（保证离线/无 LLM 时也能跑）
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("pilot.runtime.planner")


KNOWN_TOOLS = {
    "im.fetch_thread",
    "doc.create",
    "doc.append",
    "canvas.create",
    "canvas.add_shape",
    "slide.generate",
    "slide.rehearse",
    "voice.transcribe",
    "archive.bundle",
    "sync.broadcast",
    "mentor.clarify",
    "mentor.summarize",
    "bitable.search",
    # V1.5 新增
    "web.search",
    "media.tts",
    "lark.im.fetch_thread",
    "lark.doc.search",
    "lark.bitable.search",
}


_TIMELY_RE = re.compile(
    r"(最新|当前|近期|最近|本周|本月|今日|今年|去年|"
    r"2026|2025|2024|今天|昨天|前天|刚才)"
)


@dataclass
class PlanStep:
    step_id: str
    tool: str
    description: str
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    parallel_group: Optional[str] = None
    status: str = "pending"
    started_ts: int = 0
    finished_ts: int = 0
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Plan:
    plan_id: str
    user_open_id: str
    intent: str
    steps: list[PlanStep] = field(default_factory=list)
    created_ts: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "user_open_id": self.user_open_id,
            "intent": self.intent,
            "created_ts": self.created_ts,
            "meta": self.meta,
            "steps": [s.to_dict() for s in self.steps],
        }

    def find_step(self, step_id: str) -> Optional[PlanStep]:
        for s in self.steps:
            if s.step_id == step_id:
                return s
        return None

    def ready_steps(self) -> list[PlanStep]:
        finished = {s.step_id for s in self.steps if s.status in ("done", "failed", "skipped")}
        ready: list[PlanStep] = []
        for s in self.steps:
            if s.status != "pending":
                continue
            if all(dep in finished for dep in s.depends_on):
                ready.append(s)
        return ready


PLANNER_SYSTEM_PROMPT = """你是 Agent-Pilot 的规划器。
用户在飞书 IM 里用自然语言下达指令；你的任务是把它拆成一个 DAG（有向无环图），每个节点是一次工具调用。

可用工具:
[内置]
- web.search           : 联网搜索最新资料（DDG/Bing 兜底）。命中"最新/今年/趋势/进展"等时务必用作首步。
- doc.create           : 创建飞书 Docx 文档（参数 title）
- doc.append           : 往文档追加内容（参数 doc_token；markdown 留空由工具自动生成）
- canvas.create        : 创建画布/白板（参数 title）；工具会基于上游 doc.append 自动设计架构图
- canvas.add_shape     : 在画布上添加形状
- slide.generate       : 生成演示稿（真 .pptx + Slidev HTML + 演讲稿）
- slide.rehearse       : 为每页生成演讲稿
- voice.transcribe     : 语音转文字
- archive.bundle       : 汇总文档+画布+PPT，生成分享链接
- sync.broadcast       : 把状态广播到所有客户端
- mentor.clarify       : 意图模糊时主动澄清
- mentor.summarize     : 对一段对话做结构化总结
- media.tts            : 文本转语音（默认禁用，AGENT_PILOT_ENABLE_TTS=1 才启）
[飞书 OpenAPI 真集成]
- lark.im.fetch_thread : 拉取当前/指定群聊最近 N 条消息
- lark.doc.search      : 检索用户云文档
- lark.bitable.search  : 多维表格记录检索

要求:
1. 输出严格 JSON: {"steps":[{"step_id":"...","tool":"...","description":"...","args":{...},"depends_on":["..."],"parallel_group":"..."}]}
2. step_id 用 s1/s2/... 简短格式
3. depends_on 只能指向前面的 step_id
4. parallel_group 相同的步骤可并行
5. 含"最新/今年/趋势/进展"等时效词 → 第 0 步必须 web.search，并把 ${s0.results} 透传给下游 doc.append/slide.generate 的 search_results 参数
6. 含"群聊/讨论/对话/上周" → 第 0 步用 lark.im.fetch_thread
7. 含"现有文档/已有方案" → 第 0 步用 lark.doc.search
8. 含"多维表格/数据/记录" → 用 lark.bitable.search
9. 若意图模糊，首步必须是 mentor.clarify；最后一步必须是 archive.bundle
10. slide.generate / canvas.create 必须 depends_on 最后一个 doc.append（保证内容一致）
11. doc.append / slide.generate / canvas.create 的 markdown/outline 参数务必留空，工具会自动用 LLM 生成

## Few-Shot 8 例

[1] 「帮我写一份关于 AI Agent 发展趋势的报告」
{"steps":[
  {"step_id":"s1","tool":"doc.create","args":{"title":"AI Agent 发展趋势报告"},"depends_on":[]},
  {"step_id":"s2","tool":"doc.append","args":{"doc_token":"${s1.doc_token}"},"depends_on":["s1"]},
  {"step_id":"s3","tool":"archive.bundle","args":{},"depends_on":["s2"]}
]}

[2] 「OpenClaw 三件套」
{"steps":[
  {"step_id":"s1","tool":"web.search","args":{"query":"OpenClaw 飞书 开源"},"depends_on":[]},
  {"step_id":"s2","tool":"doc.create","args":{"title":"OpenClaw 介绍"},"depends_on":["s1"]},
  {"step_id":"s3","tool":"doc.append","args":{"doc_token":"${s2.doc_token}","search_results":"${s1.results}"},"depends_on":["s2"]},
  {"step_id":"s4","tool":"canvas.create","args":{"title":"OpenClaw 架构图"},"depends_on":["s3"],"parallel_group":"g1"},
  {"step_id":"s5","tool":"slide.generate","args":{"title":"OpenClaw 介绍","search_results":"${s1.results}"},"depends_on":["s3"],"parallel_group":"g1"},
  {"step_id":"s6","tool":"slide.rehearse","args":{"slide_id":"${s5.slide_id}"},"depends_on":["s5"]},
  {"step_id":"s7","tool":"archive.bundle","args":{},"depends_on":["s4","s6"]}
]}

[3] 「今年最新 AI Agent 趋势汇报 PPT」
{"steps":[
  {"step_id":"s1","tool":"web.search","args":{"query":"2026 AI Agent 最新趋势"},"depends_on":[]},
  {"step_id":"s2","tool":"slide.generate","args":{"title":"AI Agent 趋势汇报","search_results":"${s1.results}"},"depends_on":["s1"]},
  {"step_id":"s3","tool":"slide.rehearse","args":{"slide_id":"${s2.slide_id}"},"depends_on":["s2"]},
  {"step_id":"s4","tool":"archive.bundle","args":{},"depends_on":["s3"]}
]}

[4] 「把上周群里讨论的活动方案整理出来」
{"steps":[
  {"step_id":"s1","tool":"lark.im.fetch_thread","args":{"limit":80},"depends_on":[]},
  {"step_id":"s2","tool":"doc.create","args":{"title":"活动方案"},"depends_on":["s1"]},
  {"step_id":"s3","tool":"doc.append","args":{"doc_token":"${s2.doc_token}","context":"${s1.messages}"},"depends_on":["s2"]},
  {"step_id":"s4","tool":"archive.bundle","args":{},"depends_on":["s3"]}
]}

[5] 「把已有的 PRD 转成 8 页 PPT」
{"steps":[
  {"step_id":"s1","tool":"lark.doc.search","args":{"query":"PRD"},"depends_on":[]},
  {"step_id":"s2","tool":"slide.generate","args":{"title":"PRD 演示稿","pages":8},"depends_on":["s1"]},
  {"step_id":"s3","tool":"slide.rehearse","args":{"slide_id":"${s2.slide_id}"},"depends_on":["s2"]},
  {"step_id":"s4","tool":"archive.bundle","args":{},"depends_on":["s3"]}
]}

[6] 「用多维表格里的销售数据做月报」
{"steps":[
  {"step_id":"s1","tool":"lark.bitable.search","args":{"query":"销售"},"depends_on":[]},
  {"step_id":"s2","tool":"doc.create","args":{"title":"销售月报"},"depends_on":["s1"]},
  {"step_id":"s3","tool":"doc.append","args":{"doc_token":"${s2.doc_token}","data":"${s1.records}"},"depends_on":["s2"]},
  {"step_id":"s4","tool":"archive.bundle","args":{},"depends_on":["s3"]}
]}

[7] 「帮我做个汇报」（信息严重不足）
{"steps":[
  {"step_id":"s0","tool":"mentor.clarify","args":{"questions":["要汇报什么主题？","汇报对象是谁？","希望几页 PPT？"]},"depends_on":[]},
  {"step_id":"s1","tool":"archive.bundle","args":{},"depends_on":["s0"]}
]}

[8] 「产品方案 + 架构图 + 评审 PPT」
{"steps":[
  {"step_id":"s1","tool":"doc.create","args":{"title":"产品方案"},"depends_on":[]},
  {"step_id":"s2","tool":"doc.append","args":{"doc_token":"${s1.doc_token}"},"depends_on":["s1"]},
  {"step_id":"s3","tool":"canvas.create","args":{"title":"产品架构图"},"depends_on":["s2"],"parallel_group":"g1"},
  {"step_id":"s4","tool":"slide.generate","args":{"title":"产品方案"},"depends_on":["s2"],"parallel_group":"g1"},
  {"step_id":"s5","tool":"slide.rehearse","args":{"slide_id":"${s4.slide_id}"},"depends_on":["s4"]},
  {"step_id":"s6","tool":"archive.bundle","args":{},"depends_on":["s3","s5"]}
]}
"""


# ── 规划主接口 ──────────────────────────────────────────────────────────────


PlannerLLMFn = Callable[[str], Optional[dict[str, Any]]]  # text → JSON dict | None


def plan_from_intent(
    intent: str,
    *,
    user_open_id: str = "",
    meta: dict[str, Any] | None = None,
    llm_fn: PlannerLLMFn | None = None,
) -> Plan:
    """主入口：意图 → Plan.

    联网搜索现在由 ResearchAgent 在 Multi-Agent Pipeline 中自动处理，
    planner 不再注入 web.search 步骤。
    """
    intent = (intent or "").strip()
    if not intent:
        raise ValueError("intent must not be empty")

    meta_dict = dict(meta or {})
    plan_id = f"plan_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    needs_web = bool(meta_dict.get("needs_web_search")) or bool(_TIMELY_RE.search(intent))

    steps = _plan_with_llm(intent, llm_fn) if llm_fn else []
    if not steps:
        steps = _plan_heuristic(intent)

    if not any(s.tool == "archive.bundle" for s in steps):
        last_ids = [s.step_id for s in steps]
        steps.append(
            PlanStep(
                step_id=f"s{len(steps) + 1}",
                tool="archive.bundle",
                description="汇总产物，生成飞书分享链接",
                depends_on=last_ids[-2:] if len(last_ids) >= 2 else last_ids,
            )
        )

    meta_dict["needs_web_search"] = needs_web
    return Plan(
        plan_id=plan_id,
        user_open_id=user_open_id,
        intent=intent,
        steps=steps,
        created_ts=int(time.time()),
        meta=meta_dict,
    )


def _inject_web_search(steps: list[PlanStep], intent: str) -> list[PlanStep]:
    """No-op: 联网搜索现在由 ResearchAgent 在 pipeline 中自动处理."""
    return steps


# ── LLM 路径 ────────────────────────────────────────────────────────────────


def _plan_with_llm(intent: str, llm_fn: PlannerLLMFn) -> list[PlanStep]:
    try:
        obj = llm_fn(f"{PLANNER_SYSTEM_PROMPT}\n\n用户意图：{intent}\n\n请返回 JSON 规划。")
    except Exception as e:
        logger.debug("planner LLM failed: %s", e)
        return []

    if not obj or not isinstance(obj, dict) or "steps" not in obj:
        return []

    out: list[PlanStep] = []
    for i, s in enumerate(obj.get("steps", []), start=1):
        if not isinstance(s, dict):
            continue
        tool = s.get("tool", "")
        if tool not in KNOWN_TOOLS:
            logger.warning("planner produced unknown tool=%s, skipping", tool)
            continue
        out.append(
            PlanStep(
                step_id=s.get("step_id") or f"s{i}",
                tool=tool,
                description=s.get("description", ""),
                args=s.get("args", {}) or {},
                depends_on=s.get("depends_on", []) or [],
                parallel_group=s.get("parallel_group"),
            )
        )
    return out


# ── 启发式回退 ──────────────────────────────────────────────────────────────


def _title_from_intent(intent: str, suffix: str) -> str:
    trimmed = re.sub(r"[\n\r]+", " ", intent).strip()[:24]
    return f"[Agent-Pilot] {trimmed} · {suffix}"


def _plan_heuristic(intent: str, *, needs_web_search: bool = False) -> list[PlanStep]:
    want_doc = bool(re.search(r"(文档|文稿|方案|需求|纪要|总结|报告|介绍|写)", intent))
    want_canvas = bool(re.search(r"(画布|白板|流程图|架构图|画图|思维导图)", intent))
    want_slide = bool(re.search(r"(PPT|演示|演讲|slide|汇报|幻灯)", intent, re.I))
    want_fetch = bool(re.search(r"(群聊|讨论|对话|本周|昨天|最近)", intent))

    if not any([want_doc, want_canvas, want_slide]):
        want_doc = True
        want_slide = True

    steps: list[PlanStep] = []
    web_id: Optional[str] = None
    last_id: Optional[str] = None
    doc_append_id: Optional[str] = None

    # web.search 不再由 planner 注入，联网搜索由 ResearchAgent 在 pipeline 中处理

    if want_fetch:
        sid = f"s{len(steps) + 1}"
        steps.append(PlanStep(step_id=sid, tool="im.fetch_thread",
                              description="拉取最近群聊/对话作为上下文",
                              args={"limit": 50},
                              depends_on=[last_id] if last_id else []))
        last_id = sid

    if want_doc:
        sid = f"s{len(steps) + 1}"
        steps.append(PlanStep(step_id=sid, tool="doc.create",
                              description="创建飞书 Docx 文档",
                              args={"title": _title_from_intent(intent, "文档")},
                              depends_on=[last_id] if last_id else []))
        doc_create_id = sid
        sid2 = f"s{len(steps) + 1}"
        append_args: dict[str, Any] = {
            "doc_token": f"${{{doc_create_id}.doc_token}}",
            "intent": intent,
        }
        if web_id:
            append_args["search_results"] = f"${{{web_id}.results}}"
        steps.append(PlanStep(step_id=sid2, tool="doc.append",
                              description="向文档追加 AI 自动生成的详细内容" + ("（含联网资料）" if web_id else ""),
                              args=append_args,
                              depends_on=[doc_create_id]))
        doc_append_id = sid2

    if want_canvas:
        sid = f"s{len(steps) + 1}"
        deps = [doc_append_id] if doc_append_id else ([last_id] if last_id else [])
        steps.append(PlanStep(step_id=sid, tool="canvas.create",
                              description="基于文档内容创建结构化画布/架构图",
                              args={"title": _title_from_intent(intent, "画布"), "intent": intent},
                              depends_on=deps,
                              parallel_group="g1"))

    if want_slide:
        sid = f"s{len(steps) + 1}"
        deps = [doc_append_id] if doc_append_id else ([last_id] if last_id else [])
        slide_args: dict[str, Any] = {
            "title": _title_from_intent(intent, "演示稿"),
            "intent": intent,
        }
        if web_id:
            slide_args["search_results"] = f"${{{web_id}.results}}"
        steps.append(PlanStep(step_id=sid, tool="slide.generate",
                              description="基于文档内容生成演示稿（真 PPTX + HTML + 演讲稿）" + ("（含联网资料）" if web_id else ""),
                              args=slide_args,
                              depends_on=deps,
                              parallel_group="g1"))
        slide_id_ref = sid
        sid2 = f"s{len(steps) + 1}"
        steps.append(PlanStep(step_id=sid2, tool="slide.rehearse",
                              description="为 PPT 生成演讲稿",
                              args={"slide_id": f"${{{slide_id_ref}.slide_id}}"},
                              depends_on=[slide_id_ref]))

    all_ids = [s.step_id for s in steps]
    sid = f"s{len(steps) + 1}"
    steps.append(PlanStep(step_id=sid, tool="archive.bundle",
                          description="汇总产物，生成飞书分享链接",
                          args={},
                          depends_on=all_ids[-2:] if len(all_ids) >= 2 else all_ids))
    return steps
