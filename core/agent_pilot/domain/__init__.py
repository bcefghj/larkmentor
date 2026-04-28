"""Agent-Pilot 领域层 (DDD)

PRD §6 §7 §10 的工程兑现：
- ``task.py`` Task 实体 + lifecycle metadata
- ``state_machine.py`` 10 状态枚举 + 合法转移表
- ``plan.py`` Plan + PlanStep DAG（与 ``..planner.Plan`` 互补，新模型显式带 owner）
- ``artifact.py`` 产出物（doc / canvas / slide / recording / archive）
- ``context_pack.py`` PRD §7.4 标准上下文契约
- ``owner.py`` Q6 轻量指派规则
- ``events.py`` 领域事件（被 ``..application.task_service`` 订阅）
- ``errors.py`` 领域异常

设计原则：
1. **纯 Python，零外部依赖**——领域层不允许 import lark-oapi / openai / fastapi
2. **不可变 / 显式 transition**——状态变更必须通过 ``state_machine.transition()``
3. **JSON 可序列化**——所有 dataclass 都能 ``asdict()`` 直接写 ``data/tasks/``

下游：
- ``..application.task_service`` 用例编排
- ``..application.intent_detector`` 主动识别后产出 ``Task(state=SUGGESTED)``
- ``...mcp_server.tools`` 暴露 ``pilot_*`` 工具
- ``....bot.cards`` 渲染卡片
- ``.....dashboard`` 渲染任务列表/详情
"""
from .task import Task
from .state_machine import TaskState, TaskEvent, transition, can_transition
from .plan import Plan, PlanStep
from .artifact import Artifact, ArtifactKind
from .context_pack import (
    ContextPack,
    MaterialKind,
    SourceMessage,
    SourceDoc,
    UserMaterial,
    OutputRequirements,
    Constraints,
)
from .owner import OwnerAssignment, OwnerLock
from .events import DomainEvent, EventBus, default_event_bus
from .errors import (
    DomainError,
    InvalidTransitionError,
    OwnerLockedError,
    ContextNotReadyError,
)

__all__ = [
    "Task",
    "TaskState",
    "TaskEvent",
    "transition",
    "can_transition",
    "Plan",
    "PlanStep",
    "Artifact",
    "ArtifactKind",
    "ContextPack",
    "MaterialKind",
    "SourceMessage",
    "SourceDoc",
    "UserMaterial",
    "OutputRequirements",
    "Constraints",
    "OwnerAssignment",
    "OwnerLock",
    "DomainEvent",
    "EventBus",
    "default_event_bus",
    "DomainError",
    "InvalidTransitionError",
    "OwnerLockedError",
    "ContextNotReadyError",
]
