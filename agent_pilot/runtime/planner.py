"""Pilot Planner v13 – LLM-backed DAG planner with robust fallback.

Improvements over v12:
- Few-shot examples baked into the system prompt for higher LLM hit rate
- Robust JSON parsing via ``agent_pilot.llm.safe_json``
- Heuristic fallback always emits ``slide.generate depends_on`` last
  ``doc.append`` so PPT can read the document's markdown_content
- Uses ``slide.generate`` with empty outline by default (slide_tool will
  derive outline from doc markdown automatically)
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from agent_pilot.llm.safe_json import safe_json_parse

logger = logging.getLogger("agent_pilot.runtime.planner")


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
}


@dataclass
class PlanStep:
    step_id: str
    tool: str
    description: str
    args: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    parallel_group: Optional[str] = None
    status: str = "pending"
    started_ts: int = 0
    finished_ts: int = 0
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Plan:
    plan_id: str
    user_open_id: str
    intent: str
    steps: List[PlanStep] = field(default_factory=list)
    created_ts: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
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

    def ready_steps(self) -> List[PlanStep]:
        finished = {s.step_id for s in self.steps if s.status in ("done", "failed")}
        ready: List[PlanStep] = []
        for s in self.steps:
            if s.status != "pending":
                continue
            if all(dep in finished for dep in s.depends_on):
                ready.append(s)
        return ready


_PLANNER_SYSTEM_PROMPT = """你是 Agent-Pilot 的规划器。用户在飞书 IM 里用自然语言下达指令，
你的任务是把它拆成一个 DAG（有向无环图），每个节点是一次工具调用。

可用工具（务必从以下集合中选择）：
- im.fetch_thread      : 拉取当前或指定群聊的最近上下文（参数 chat_id, limit）
- doc.create           : 创建飞书 Docx 文档（参数 title）
- doc.append           : 往已创建文档追加内容。markdown 参数留空，工具内部会用 AI 自动生成（参数 doc_token, markdown）
- canvas.create        : 创建画布/白板（参数 title）。工具会基于上游 doc.append 的 markdown 自动设计架构图
- canvas.add_shape     : 在画布上添加形状（参数 canvas_id, shape_type, text, x, y）
- slide.generate       : 生成演示稿（真 .pptx 文件 + Slidev HTML + 演讲稿 mp3）。outline 参数留空，工具会从上游 doc.append 的 markdown 自动提炼大纲（参数 title, outline）
- slide.rehearse       : 为每页生成演讲稿（参数 slide_id）
- voice.transcribe     : 语音转文字（参数 audio_url 或 file_key）
- archive.bundle       : 汇总文档+画布+PPT，生成分享链接（参数 artifacts: [id...]）
- sync.broadcast       : 把最新状态广播到所有客户端（自动）
- mentor.clarify       : 如果意图模糊主动问用户（参数 questions）
- mentor.summarize     : 对一段对话做结构化总结（参数 context）

要求：
1. 输出严格 JSON，形如 {"steps": [ {"step_id": "...", "tool": "...", "description": "...",
   "args": {...}, "depends_on": ["..."], "parallel_group": "..."} ]}。
2. step_id 用 s1 / s2 这种简短格式。
3. depends_on 只能指向前面的 step_id。
4. parallel_group 相同的步骤可以并行执行。
5. 若意图模糊，首个 step 必须是 mentor.clarify。
6. 最后一步必须是 archive.bundle。
7. **slide.generate 和 canvas.create 必须 depends_on 最后一个 doc.append**，
   这样 PPT/画布能基于文档内容生成，保持一致性。
8. doc.append / slide.generate / canvas.create 的内容参数（markdown / outline）务必留空，
   工具会自动用 LLM 生成。

## Few-Shot 示例

意图："帮我写一份关于 AI Agent 发展趋势的报告"
正确规划：
{"steps":[
  {"step_id":"s1","tool":"doc.create","description":"创建飞书 Docx","args":{"title":"AI Agent 发展趋势报告"},"depends_on":[]},
  {"step_id":"s2","tool":"doc.append","description":"AI 自动生成详细报告内容","args":{"doc_token":"${s1.doc_token}"},"depends_on":["s1"]},
  {"step_id":"s3","tool":"archive.bundle","description":"汇总产物并生成分享链接","args":{},"depends_on":["s2"]}
]}

意图："产品方案 + 架构图 + 汇报 PPT 三件套"
正确规划：
{"steps":[
  {"step_id":"s1","tool":"doc.create","description":"创建产品方案文档","args":{"title":"产品方案"},"depends_on":[]},
  {"step_id":"s2","tool":"doc.append","description":"生成方案正文","args":{"doc_token":"${s1.doc_token}"},"depends_on":["s1"]},
  {"step_id":"s3","tool":"canvas.create","description":"基于方案生成架构图","args":{"title":"产品架构图"},"depends_on":["s2"]},
  {"step_id":"s4","tool":"slide.generate","description":"基于方案生成 PPT","args":{"title":"产品方案"},"depends_on":["s2"]},
  {"step_id":"s5","tool":"slide.rehearse","description":"为 PPT 生成演讲稿","args":{"slide_id":"${s4.slide_id}"},"depends_on":["s4"]},
  {"step_id":"s6","tool":"archive.bundle","description":"汇总","args":{},"depends_on":["s3","s5"]}
]}

意图："帮我做个汇报"（信息严重不足）
正确规划：
{"steps":[
  {"step_id":"s0","tool":"mentor.clarify","description":"主动澄清","args":{"questions":["要汇报什么主题？","汇报对象是谁？","希望几页 PPT？"]},"depends_on":[]},
  {"step_id":"s1","tool":"archive.bundle","description":"占位，澄清后用户重新触发","args":{},"depends_on":["s0"]}
]}
"""


class PilotPlanner:
    def __init__(self, chat_json_fn=None):
        self._chat_json = chat_json_fn

    def plan(
        self,
        intent: str,
        *,
        user_open_id: str = "",
        meta: Optional[Dict[str, Any]] = None,
        allow_clarify: bool = True,
    ) -> Plan:
        intent = (intent or "").strip()
        if not intent:
            raise ValueError("intent must not be empty")

        plan_id = f"plan_{int(time.time())}_{uuid.uuid4().hex[:6]}"

        clarify_step: Optional[PlanStep] = None
        if allow_clarify:
            try:
                from core.agent_pilot.advanced import diagnose_intent

                decision = diagnose_intent(intent)
                if decision.should_clarify:
                    clarify_step = PlanStep(
                        step_id="s0",
                        tool="mentor.clarify",
                        description="意图模糊 → Agent 主动澄清",
                        args={"intent": intent, "questions": decision.questions},
                    )
            except Exception as e:
                logger.debug("clarify diagnosis skipped: %s", e)

        steps = self._plan_with_llm(intent)
        if not steps:
            logger.info("planner fallback: heuristic for intent=%s", intent[:60])
            steps = self._plan_heuristic(intent)

        if clarify_step is not None:
            for s in steps:
                if not s.depends_on:
                    s.depends_on = [clarify_step.step_id]
            steps = [clarify_step] + steps

        # Ensure archive.bundle is the last step
        if not any(s.tool == "archive.bundle" for s in steps):
            last_ids = [s.step_id for s in steps]
            steps.append(
                PlanStep(
                    step_id=f"s{len(steps) + 1}",
                    tool="archive.bundle",
                    description="汇总产出并生成分享链接",
                    depends_on=last_ids[-2:] if len(last_ids) >= 2 else last_ids,
                )
            )

        return Plan(
            plan_id=plan_id,
            user_open_id=user_open_id,
            intent=intent,
            steps=steps,
            created_ts=int(time.time()),
            meta=meta or {},
        )

    # ── LLM path with safe JSON parsing ──

    def _plan_with_llm(self, intent: str) -> List[PlanStep]:
        try:
            if self._chat_json is not None:
                fn = self._chat_json
                obj = fn(f"{_PLANNER_SYSTEM_PROMPT}\n\n用户意图：{intent}\n\n请返回 JSON 规划。", temperature=0.2)
            else:
                from llm.llm_client import chat as _chat

                raw = _chat(
                    f"{_PLANNER_SYSTEM_PROMPT}\n\n用户意图：{intent}\n\n请返回 JSON 规划，不要任何前缀。",
                    temperature=0.2,
                    max_tokens=4096,
                )
                obj = safe_json_parse(raw, expected_type=dict, debug_label="planner")
        except Exception as e:
            logger.debug("planner LLM call failed: %s", e)
            return []

        if not obj or not isinstance(obj, dict) or "steps" not in obj:
            return []

        steps: List[PlanStep] = []
        for i, s in enumerate(obj.get("steps", []), start=1):
            tool = s.get("tool", "")
            if tool not in KNOWN_TOOLS:
                logger.warning("planner produced unknown tool=%s, skipping", tool)
                continue
            steps.append(
                PlanStep(
                    step_id=s.get("step_id") or f"s{i}",
                    tool=tool,
                    description=s.get("description", ""),
                    args=s.get("args", {}) or {},
                    depends_on=s.get("depends_on", []) or [],
                    parallel_group=s.get("parallel_group"),
                )
            )
        return steps

    # ── Heuristic fallback ──

    def _plan_heuristic(self, intent: str) -> List[PlanStep]:
        want_doc = bool(re.search(r"(文档|文稿|方案|需求|纪要|总结|报告|介绍|写)", intent))
        want_canvas = bool(re.search(r"(画布|白板|流程图|架构图|画图|思维导图)", intent))
        want_slide = bool(re.search(r"(PPT|演示|演讲|slide|汇报|幻灯)", intent, re.I))
        want_fetch = bool(re.search(r"(群聊|讨论|对话|本周|昨天|最近)", intent))

        if not any([want_doc, want_canvas, want_slide]):
            want_doc = True
            want_slide = True

        steps: List[PlanStep] = []
        last_id: Optional[str] = None
        doc_append_id: Optional[str] = None

        if want_fetch:
            sid = f"s{len(steps) + 1}"
            steps.append(
                PlanStep(
                    step_id=sid,
                    tool="im.fetch_thread",
                    description="拉取最近群聊/对话作为上下文",
                    args={"limit": 50},
                )
            )
            last_id = sid

        if want_doc:
            sid = f"s{len(steps) + 1}"
            steps.append(
                PlanStep(
                    step_id=sid,
                    tool="doc.create",
                    description="创建飞书 Docx 文档",
                    args={"title": _title_from_intent(intent, "文档")},
                    depends_on=[last_id] if last_id else [],
                )
            )
            doc_create_id = sid
            sid2 = f"s{len(steps) + 1}"
            steps.append(
                PlanStep(
                    step_id=sid2,
                    tool="doc.append",
                    description="向文档追加 AI 自动生成的详细内容",
                    args={"doc_token": f"${{{doc_create_id}.doc_token}}"},
                    depends_on=[doc_create_id],
                )
            )
            doc_append_id = sid2

        if want_canvas:
            sid = f"s{len(steps) + 1}"
            deps = [doc_append_id] if doc_append_id else ([last_id] if last_id else [])
            steps.append(
                PlanStep(
                    step_id=sid,
                    tool="canvas.create",
                    description="基于文档内容创建结构化画布/架构图",
                    args={"title": _title_from_intent(intent, "画布")},
                    depends_on=deps,
                )
            )
            canvas_create_id = sid
            sid2 = f"s{len(steps) + 1}"
            steps.append(
                PlanStep(
                    step_id=sid2,
                    tool="canvas.add_shape",
                    description="在画布上绘制架构框架（节点+箭头）",
                    args={"canvas_id": f"${{{canvas_create_id}.canvas_id}}", "shape_type": "frame"},
                    depends_on=[canvas_create_id],
                )
            )

        if want_slide:
            sid = f"s{len(steps) + 1}"
            deps = [doc_append_id] if doc_append_id else ([last_id] if last_id else [])
            steps.append(
                PlanStep(
                    step_id=sid,
                    tool="slide.generate",
                    description="基于文档内容生成演示稿（真 PPTX + HTML + 演讲稿）",
                    args={"title": _title_from_intent(intent, "演示稿")},
                    depends_on=deps,
                )
            )
            slide_id = sid
            sid2 = f"s{len(steps) + 1}"
            steps.append(
                PlanStep(
                    step_id=sid2,
                    tool="slide.rehearse",
                    description="为 PPT 生成演讲稿",
                    args={"slide_id": f"${{{slide_id}.slide_id}}"},
                    depends_on=[slide_id],
                )
            )

        all_ids = [s.step_id for s in steps]
        sid = f"s{len(steps) + 1}"
        steps.append(
            PlanStep(
                step_id=sid,
                tool="archive.bundle",
                description="汇总产物，生成飞书分享链接",
                args={},
                depends_on=all_ids[-2:] if len(all_ids) >= 2 else all_ids,
            )
        )
        return steps


def _title_from_intent(intent: str, suffix: str) -> str:
    trimmed = re.sub(r"[\n\r]+", " ", intent).strip()
    trimmed = trimmed[:24]
    return f"[Agent-Pilot] {trimmed} · {suffix}"


_default_planner: Optional[PilotPlanner] = None


def default_planner() -> PilotPlanner:
    global _default_planner
    if _default_planner is None:
        _default_planner = PilotPlanner()
    return _default_planner


def plan_from_intent(intent: str, *, user_open_id: str = "", meta: Optional[Dict[str, Any]] = None) -> Plan:
    return default_planner().plan(intent, user_open_id=user_open_id, meta=meta)
