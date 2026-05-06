"""域模型 — Session / Task / Artifact / Step.

按 Modern Agent Harness Blueprint 2026 推荐的 4 个核心实体设计，
每个实体都可序列化为 JSON 便于落盘 / replay / debug。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


# ── Session ─────────────────────────────────────────────────────────────────


class SessionMode(str, Enum):
    """Session 当前模式."""

    PLAN = "plan"
    EXECUTE = "execute"
    REVIEW = "review"


def _ts() -> int:
    return int(time.time())


def _new_id(prefix: str) -> str:
    return f"{prefix}_{_ts()}_{uuid.uuid4().hex[:6]}"


@dataclass
class Session:
    """A session 是一条可恢复的"对话/任务"主线.

    关键不变量:
      - session_id 全局唯一
      - thread_id 与外部 IM 线程绑定（飞书 chat_id + msg_id）
      - mode 状态机：plan ↔ execute ↔ review
      - tool_catalog_version 决定本 session 可见的工具集（缓存稳定）
    """

    session_id: str = field(default_factory=lambda: _new_id("sess"))
    thread_id: str = ""
    user_open_id: str = ""
    chat_id: str = ""
    tenant_id: str = "default"
    workspace_id: str = ""

    created_at: int = field(default_factory=_ts)
    updated_at: int = field(default_factory=_ts)

    mode: SessionMode = SessionMode.EXECUTE
    model_profile: str = "orchestrator-default"
    tool_catalog_version: str = "v1"
    approval_mode: str = "ask"  # auto | ask | strict

    context_state: dict[str, Any] = field(default_factory=lambda: {
        "compacted": False,
        "recent_summary_ref": "",
        "tokens_used": 0,
    })

    meta: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = _ts()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["mode"] = self.mode.value
        return d


# ── Task ────────────────────────────────────────────────────────────────────


class TaskState(str, Enum):
    """PRD §10 任务状态机."""

    SUGGESTED = "suggested"
    ASSIGNED = "assigned"
    CONTEXT_PENDING = "context_pending"
    PLANNING = "planning"
    DOC_GENERATING = "doc_generating"
    PPT_GENERATING = "ppt_generating"
    REVIEWING = "reviewing"
    DELIVERED = "delivered"
    PAUSED = "paused"
    FAILED = "failed"
    IGNORED = "ignored"


STAGES = ("context", "doc", "ppt", "rehearse")


# 合法转移图（PRD §10）：
#   suggested → assigned/ignored
#   assigned → context_pending/planning（信息已足时直接 planning）/ignored
#   context_pending → planning/ignored
#   planning → doc_generating/ppt_generating/failed
#   doc_generating → ppt_generating/reviewing/failed
#   ppt_generating → reviewing/failed
#   reviewing → delivered/failed/paused
#   delivered → reviewing（重做）/ignored
#   paused → planning/doc_generating/ppt_generating/reviewing/ignored
#   failed → planning（重试）/ignored
#   ignored → suggested（重新激活）
LEGAL_TRANSITIONS: dict["TaskState", set["TaskState"]] = {
    TaskState.SUGGESTED: {TaskState.ASSIGNED, TaskState.IGNORED},
    TaskState.ASSIGNED: {TaskState.CONTEXT_PENDING, TaskState.PLANNING, TaskState.IGNORED, TaskState.PAUSED},
    TaskState.CONTEXT_PENDING: {TaskState.PLANNING, TaskState.IGNORED, TaskState.PAUSED},
    TaskState.PLANNING: {
        TaskState.DOC_GENERATING,
        TaskState.PPT_GENERATING,
        TaskState.FAILED,
        TaskState.PAUSED,
    },
    TaskState.DOC_GENERATING: {
        TaskState.PPT_GENERATING,
        TaskState.REVIEWING,
        TaskState.FAILED,
        TaskState.PAUSED,
    },
    TaskState.PPT_GENERATING: {TaskState.REVIEWING, TaskState.FAILED, TaskState.PAUSED},
    TaskState.REVIEWING: {TaskState.DELIVERED, TaskState.FAILED, TaskState.PAUSED},
    TaskState.DELIVERED: {TaskState.REVIEWING, TaskState.IGNORED},
    TaskState.PAUSED: {
        TaskState.PLANNING,
        TaskState.DOC_GENERATING,
        TaskState.PPT_GENERATING,
        TaskState.REVIEWING,
        TaskState.IGNORED,
    },
    TaskState.FAILED: {TaskState.PLANNING, TaskState.IGNORED},
    TaskState.IGNORED: {TaskState.SUGGESTED},
}


class IllegalTransitionError(ValueError):
    """非法状态转移；调用方需根据业务决定降级 / 报错."""


@dataclass
class Task:
    """A task 是协调对象.

    覆盖 PRD §6 (owner) + §10 (状态机) + §11 (用户旅程).
    """

    task_id: str = field(default_factory=lambda: _new_id("task"))
    session_id: str = ""

    title: str = ""
    intent: str = ""
    state: TaskState = TaskState.SUGGESTED

    owner_open_id: str = ""
    owner_locked: bool = False  # 进入执行后锁定（PRD §6.3）
    assignees: list[str] = field(default_factory=list)
    stage_owners: dict[str, str] = field(default_factory=dict)  # stage -> open_id

    plan_id: str = ""
    artifact_refs: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)

    source_chat_id: str = ""
    source_msg_id: str = ""
    detected_at: int = field(default_factory=_ts)
    updated_at: int = field(default_factory=_ts)

    meta: dict[str, Any] = field(default_factory=dict)

    def transition(self, new_state: TaskState, *, force: bool = False) -> None:
        """状态迁移；非法转移默认抛 IllegalTransitionError，可用 force=True 跳过校验."""
        if not force:
            allowed = LEGAL_TRANSITIONS.get(self.state, set())
            if new_state == self.state:
                self.updated_at = _ts()
                return
            if new_state not in allowed:
                raise IllegalTransitionError(
                    f"非法转移 {self.state.value} → {new_state.value}；合法目标={[s.value for s in allowed]}"
                )
        self.state = new_state
        self.updated_at = _ts()

    def transition_to(self, new_state: TaskState) -> None:
        """transition() 的别名，匹配 PRD §10 命名."""
        self.transition(new_state)

    def can_transition_to(self, new_state: TaskState) -> bool:
        return new_state in LEGAL_TRANSITIONS.get(self.state, set())

    def set_stage_owner(self, stage: str, owner_open_id: str) -> None:
        if stage not in STAGES:
            raise ValueError(f"未知 stage={stage}；合法值={STAGES}")
        self.stage_owners[stage] = owner_open_id
        self.updated_at = _ts()

    def lock_owner(self, owner_open_id: str) -> None:
        self.owner_open_id = owner_open_id
        self.owner_locked = True
        self.updated_at = _ts()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d


# ── Artifact ────────────────────────────────────────────────────────────────


@dataclass
class ArtifactRef:
    """轻量 handle：仅 URI + 类型，不内嵌内容（filesystem as working memory）."""

    uri: str
    mime_type: str
    summary: str = ""
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Artifact:
    """持久化 artifact — 大段内容、文件、链接均落盘后用 ArtifactRef 引用."""

    artifact_id: str = field(default_factory=lambda: _new_id("artifact"))
    uri: str = ""  # artifact://reports/xxx.json | https://feishu.cn/docx/xxx | /local/path.pptx
    mime_type: str = "application/json"
    summary: str = ""
    sha256: str = ""

    source: dict[str, Any] = field(default_factory=dict)  # tool / session_id / step_id
    created_at: int = field(default_factory=_ts)
    size_bytes: int = 0

    def to_ref(self) -> ArtifactRef:
        return ArtifactRef(uri=self.uri, mime_type=self.mime_type, summary=self.summary, sha256=self.sha256)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Step ────────────────────────────────────────────────────────────────────


class StepKind(str, Enum):
    """Step 类型 — Claude Code 8 步 loop 的节点类型."""

    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    PERMISSION_CHECK = "permission_check"
    CONTEXT_RESET = "context_reset"
    HANDOFF = "handoff"
    USER_INPUT = "user_input"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    DENIED = "denied"  # 被 governance 拒绝
    AWAITING_APPROVAL = "awaiting_approval"


@dataclass
class Step:
    """单个 model decision 或 tool execution 事件."""

    step_id: str = field(default_factory=lambda: _new_id("step"))
    session_id: str = ""
    task_id: str = ""

    kind: StepKind = StepKind.LLM_CALL
    tool_name: str = ""

    status: StepStatus = StepStatus.PENDING
    started_at: int = 0
    ended_at: int = 0

    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[str] = field(default_factory=list)
    error: str = ""

    duration_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0

    def start(self) -> None:
        self.status = StepStatus.RUNNING
        self.started_at = _ts()

    def complete(self, output: dict[str, Any] | None = None) -> None:
        self.status = StepStatus.COMPLETED
        self.ended_at = _ts()
        self.duration_ms = int((self.ended_at - self.started_at) * 1000)
        if output is not None:
            self.output = output

    def fail(self, error: str) -> None:
        self.status = StepStatus.FAILED
        self.ended_at = _ts()
        self.duration_ms = int((self.ended_at - self.started_at) * 1000)
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["status"] = self.status.value
        return d
