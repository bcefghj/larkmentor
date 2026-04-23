"""Pilot Planner – Scenario B (task understanding & planning).

Takes a free-form natural-language intent from the IM channel (text or
voice-transcribed) and decomposes it into a DAG of concrete tool calls
the Orchestrator can execute.

Design notes
------------
* We keep the planner LLM-optional: if ``ARK_API_KEY`` is unset we fall
  back to a **keyword-based heuristic planner** that still produces a
  reasonable DAG for the demo scenarios (doc / canvas / slide / archive).
  This keeps unit tests deterministic and means the system degrades
  gracefully if the model endpoint is down.
* The planner returns a ``Plan`` dataclass that is JSON-serialisable so
  the same DAG can be replayed / inspected on any of the 4 Flutter
  clients or the web dashboard without re-running the LLM.
* Steps can be parallel (``parallel_group``) or sequential. The
  orchestrator respects ``depends_on`` edges.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pilot.planner")


# ── Tool identifiers the planner may emit ──
# Keep these in sync with agent_pilot/tools/__init__.TOOL_REGISTRY.
KNOWN_TOOLS = {
    "im.fetch_thread",          # Scenario A: pull prior IM context
    "doc.create",               # Scenario C: create a Feishu Docx
    "doc.append",               # Scenario C: append markdown blocks
    "canvas.create",            # Scenario C: create tldraw + Feishu board
    "canvas.add_shape",         # Scenario C: insert shape/image/table
    "slide.generate",           # Scenario D: Slidev markdown → pptx
    "slide.rehearse",           # Scenario D: generate speaker notes
    "voice.transcribe",         # Scenario A: STT for voice commands
    "archive.bundle",           # Scenario F: bundle + share link
    "sync.broadcast",           # Scenario E: push to all connected clients
    "mentor.clarify",           # Advanced: proactively ask user for clarification
    "mentor.summarize",         # Advanced: summarise IM discussion
}


@dataclass
class PlanStep:
    """Single node in the execution DAG."""

    step_id: str
    tool: str
    description: str
    args: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    parallel_group: Optional[str] = None
    # Populated during execution
    status: str = "pending"       # pending / running / done / failed
    started_ts: int = 0
    finished_ts: int = 0
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Plan:
    """A DAG of PlanStep produced by the planner."""

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
        # A step is ready once all its deps have FINISHED (done OR failed).
        # Failing upstream doesn't poison the entire DAG; the tool itself
        # is responsible for dealing with missing/invalid inputs.
        finished = {s.step_id for s in self.steps if s.status in ("done", "failed")}
        ready: List[PlanStep] = []
        for s in self.steps:
            if s.status != "pending":
                continue
            if all(dep in finished for dep in s.depends_on):
                ready.append(s)
        return ready


# ── Planner implementation ──

_PLANNER_SYSTEM_PROMPT = """
你是 LarkMentor · Agent-Pilot 的规划器。用户在飞书 IM 里用自然语言下达指令，
你的任务是把它拆成一个 DAG（有向无环图），每个节点是一次工具调用。

可用工具（务必从以下集合中选择）：
- im.fetch_thread      : 拉取当前或指定群聊的最近上下文（参数 chat_id, limit）
- doc.create           : 创建飞书 Docx 文档（参数 title）
- doc.append           : 往已创建文档追加 markdown 块（参数 doc_token, markdown）
- canvas.create        : 创建白板（tldraw + 飞书画板双写）（参数 title）
- canvas.add_shape     : 在画布上添加形状（参数 canvas_id, shape_type, text, x, y）
- slide.generate       : Slidev markdown → pptx（参数 outline: [{title, bullets}]）
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
"""


class PilotPlanner:
    """LLM-backed planner with keyword fallback."""

    def __init__(self, chat_json_fn=None):
        # Allow dependency injection for tests.
        self._chat_json = chat_json_fn

    def plan(self, intent: str, *, user_open_id: str = "", meta: Optional[Dict[str, Any]] = None,
             allow_clarify: bool = True) -> Plan:
        intent = (intent or "").strip()
        if not intent:
            raise ValueError("intent must not be empty")

        plan_id = f"plan_{int(time.time())}_{uuid.uuid4().hex[:6]}"

        # Advanced Agent: decide if we should prepend a mentor.clarify step
        # to proactively ask the user before running the full DAG.
        clarify_step: Optional[PlanStep] = None
        if allow_clarify:
            try:
                from .advanced import diagnose_intent
                decision = diagnose_intent(intent)
                if decision.should_clarify:
                    clarify_step = PlanStep(
                        step_id="s0",
                        tool="mentor.clarify",
                        description="意图模糊 → Agent 主动澄清",
                        args={"intent": intent, "questions": decision.questions},
                    )
            except Exception as e:
                logger.debug("advanced clarify skipped: %s", e)

        steps = self._plan_with_llm(intent)
        if not steps:
            logger.info("planner fallback: using heuristic for intent=%s", intent[:60])
            steps = self._plan_heuristic(intent)

        # Prepend the clarify step and wire it as dependency of every root step
        if clarify_step is not None:
            existing_ids = {s.step_id for s in steps}
            # Assign unique id if collision (unlikely since we use s0)
            while clarify_step.step_id in existing_ids:
                clarify_step.step_id += "_c"
            for s in steps:
                if not s.depends_on:
                    s.depends_on = [clarify_step.step_id]
            steps = [clarify_step] + steps

        # Final sanity: guarantee archive.bundle as last step
        if not any(s.tool == "archive.bundle" for s in steps):
            last_ids = [s.step_id for s in steps]
            steps.append(PlanStep(
                step_id=f"s{len(steps)+1}",
                tool="archive.bundle",
                description="汇总产出并生成分享链接",
                depends_on=last_ids[-2:] if len(last_ids) >= 2 else last_ids,
            ))

        plan = Plan(
            plan_id=plan_id,
            user_open_id=user_open_id,
            intent=intent,
            steps=steps,
            created_ts=int(time.time()),
            meta=meta or {},
        )
        return plan

    # ── LLM path ──

    def _plan_with_llm(self, intent: str) -> List[PlanStep]:
        """Call the LLM. Returns empty list on any failure."""
        try:
            if self._chat_json is not None:
                fn = self._chat_json
            else:
                from llm.llm_client import chat_json as fn
            prompt = f"{_PLANNER_SYSTEM_PROMPT}\n\n用户意图：{intent}\n\n请返回 JSON 规划。"
            obj = fn(prompt, temperature=0.2)
        except Exception as e:
            logger.debug("planner llm disabled (%s)", e)
            return []
        if not obj or "steps" not in obj:
            return []
        steps: List[PlanStep] = []
        for i, s in enumerate(obj.get("steps", []), start=1):
            tool = s.get("tool", "")
            if tool not in KNOWN_TOOLS:
                logger.warning("planner produced unknown tool=%s, skipping", tool)
                continue
            steps.append(PlanStep(
                step_id=s.get("step_id") or f"s{i}",
                tool=tool,
                description=s.get("description", ""),
                args=s.get("args", {}) or {},
                depends_on=s.get("depends_on", []) or [],
                parallel_group=s.get("parallel_group"),
            ))
        return steps

    # ── Heuristic fallback (also used in offline tests) ──

    def _plan_heuristic(self, intent: str) -> List[PlanStep]:
        want_doc = bool(re.search(r"(文档|文稿|方案|需求|纪要|总结)", intent))
        want_canvas = bool(re.search(r"(画布|白板|流程图|架构图|画图|思维导图)", intent))
        want_slide = bool(re.search(r"(PPT|演示|演讲|slide|汇报)", intent, re.I))
        want_fetch = bool(re.search(r"(群聊|讨论|对话|本周|昨天|最近)", intent))

        if not any([want_doc, want_canvas, want_slide]):
            # Default rich flow if user just says "处理一下" / "做个方案"
            want_doc = True
            want_slide = True

        steps: List[PlanStep] = []
        last_id = None

        if want_fetch:
            sid = f"s{len(steps)+1}"
            steps.append(PlanStep(
                step_id=sid, tool="im.fetch_thread",
                description="拉取最近群聊/对话作为上下文",
                args={"limit": 50},
            ))
            last_id = sid

        parallel_ids: List[str] = []
        if want_doc:
            sid = f"s{len(steps)+1}"
            steps.append(PlanStep(
                step_id=sid, tool="doc.create",
                description="创建飞书 Docx 文档",
                args={"title": _title_from_intent(intent, "方案")},
                depends_on=[last_id] if last_id else [],
                parallel_group="artifact_build",
            ))
            parallel_ids.append(sid)
            sid2 = f"s{len(steps)+1}"
            steps.append(PlanStep(
                step_id=sid2, tool="doc.append",
                description="根据意图生成 markdown 大纲并写入文档",
                args={"doc_token": f"${{{sid}.doc_token}}"},
                depends_on=[sid],
                parallel_group="artifact_build",
            ))
            parallel_ids.append(sid2)

        if want_canvas:
            sid = f"s{len(steps)+1}"
            steps.append(PlanStep(
                step_id=sid, tool="canvas.create",
                description="创建画布（tldraw + 飞书画板）",
                args={"title": _title_from_intent(intent, "画布")},
                depends_on=[last_id] if last_id else [],
                parallel_group="artifact_build",
            ))
            parallel_ids.append(sid)
            sid2 = f"s{len(steps)+1}"
            steps.append(PlanStep(
                step_id=sid2, tool="canvas.add_shape",
                description="在画布上绘制初始框架（节点+箭头）",
                args={"canvas_id": f"${{{sid}.canvas_id}}", "shape_type": "frame"},
                depends_on=[sid],
                parallel_group="artifact_build",
            ))
            parallel_ids.append(sid2)

        if want_slide:
            sid = f"s{len(steps)+1}"
            steps.append(PlanStep(
                step_id=sid, tool="slide.generate",
                description="生成 Slidev PPT（导出 pptx + pdf）",
                args={"title": _title_from_intent(intent, "演示稿")},
                depends_on=[last_id] if last_id else [],
                parallel_group="artifact_build",
            ))
            parallel_ids.append(sid)
            sid2 = f"s{len(steps)+1}"
            steps.append(PlanStep(
                step_id=sid2, tool="slide.rehearse",
                description="为 PPT 生成演讲稿",
                args={"slide_id": f"${{{sid}.slide_id}}"},
                depends_on=[sid],
                parallel_group="artifact_build",
            ))
            parallel_ids.append(sid2)

        # Final bundle
        sid = f"s{len(steps)+1}"
        steps.append(PlanStep(
            step_id=sid, tool="archive.bundle",
            description="汇总产物，生成飞书分享链接",
            args={},
            depends_on=parallel_ids or ([last_id] if last_id else []),
        ))
        return steps


def _title_from_intent(intent: str, suffix: str) -> str:
    trimmed = re.sub(r"[\n\r]+", " ", intent).strip()
    trimmed = trimmed[:24]
    return f"[Agent-Pilot] {trimmed} · {suffix}"


# ── Module-level convenience ──

_default_planner: Optional[PilotPlanner] = None


def default_planner() -> PilotPlanner:
    global _default_planner
    if _default_planner is None:
        _default_planner = PilotPlanner()
    return _default_planner


def plan_from_intent(intent: str, *, user_open_id: str = "", meta: Optional[Dict[str, Any]] = None) -> Plan:
    """Convenience wrapper used by the bot handler."""
    return default_planner().plan(intent, user_open_id=user_open_id, meta=meta)
