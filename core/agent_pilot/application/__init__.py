"""Agent-Pilot 应用服务层（DDD application layer）.

负责用例编排——在领域层之上协调主动识别、上下文构建、规划、执行、归档等
端到端流程。每个服务都是无状态的（除了通过 Repository 访问持久化层）。

模块概览：
- ``task_service``: 任务用例（create/assign/transition/lock/archive）
- ``intent_detector``: PRD §5 主动识别（规则+LLM+闸门）
- ``context_service``: PRD §7 上下文包构建（三档资料源）
- ``planner_service``: 任务理解与规划（自动选 5 推理模式）
- ``orchestrator_service``: DAG 执行（Builder-Validator 分离）
- ``delivery_service``: 归档与分享
- ``repository``: JSON 持久化（task_repo / artifact_repo / audit_repo）
"""
from .context_service import (
    ContextService,
    ContextBuildOptions,
    default_context_service,
    parse_feishu_doc_token,
)
from .learner import (
    PilotLearner,
    TaskMemory,
    GeneratedSkill,
    default_pilot_learner,
)
from .memory_inject import (
    make_memory_resolver_adapter,
    wrap_llm_with_memory,
    attach_memory_to_default_services,
)
from .multi_agent_pipeline import MultiAgentPipeline, AgentReport, AgentTranscript
from .orchestrator_service import OrchestratorService, OrchestratorConfig
from .planner_service import (
    PlannerService,
    PatternSelection,
    ReasoningPattern,
    select_reasoning_pattern,
)
from .task_service import TaskService, default_task_service
from .intent_detector import (
    IntentDetector,
    IntentDetectorConfig,
    IntentVerdict,
    ChatMessage,
    TaskCandidate,
    CooldownManager,
)

__all__ = [
    "TaskService",
    "default_task_service",
    "IntentDetector",
    "IntentDetectorConfig",
    "IntentVerdict",
    "ChatMessage",
    "TaskCandidate",
    "CooldownManager",
    "ContextService",
    "ContextBuildOptions",
    "default_context_service",
    "parse_feishu_doc_token",
    "PlannerService",
    "PatternSelection",
    "ReasoningPattern",
    "select_reasoning_pattern",
    "OrchestratorService",
    "OrchestratorConfig",
    "MultiAgentPipeline",
    "AgentReport",
    "AgentTranscript",
    "PilotLearner",
    "TaskMemory",
    "GeneratedSkill",
    "default_pilot_learner",
    "make_memory_resolver_adapter",
    "wrap_llm_with_memory",
    "attach_memory_to_default_services",
]
