"""Claude Code-style Agent Harness for Agent-Pilot.

This package implements the "80% harness" that production-grade agents need
beyond simple LLM-orchestrated DAG execution. It is inspired by Anthropic's
Claude Code (reverse-engineered from the 510k-line source leak) and adapted
for the Feishu AI Campus Challenge Agent-Pilot competition.

Modules
-------
- orchestrator_v2   : LangGraph-style state machine
                      gather_context -> plan -> dispatch -> verify -> reflect -> replan
- context_manager   : 4-layer compression (snip / microcompact / collapse / autocompact)
- context_cascade   : 9-layer progressive compression cascade
- prompt_cache      : 3-layer prompt cache (static / session / dynamic)
- fork_executor     : Multi-Agent Fork mode for parallel exploration
- memory            : Long-term memory (AGENT_PILOT.md + Mem0g fallback)
- permissions       : 6-mode permission gate with deny-first rule ordering
- hooks             : 6 lifecycle event registry (SessionStart / PreTool / PostTool / PreCompact / Stop)
- skills_loader     : 3-layer progressive disclosure skill loader
- mcp_client        : JSON-RPC 2.0 MCP client (stdio + HTTP Streamable)
- subagent          : Isolated-context subagent runner (Task tool)
- streaming_executor: Read-write lock streaming tool dispatcher
- tool_registry     : buildTool() factory with concurrency markers

Design principles
-----------------
1. Every component works in graceful-degradation mode when dependencies
   (LangGraph, Mem0, y-py, openai) are missing.
2. State is event-sourced: every transition emits a structured event that
   downstream observers (Dashboard, Flutter, audit log) can replay.
3. Backwards compat: the legacy PilotOrchestrator delegates here when called.
"""

from .context_manager import ContextManager, ContextSnapshot
from .feature_flags import FeatureFlags, ff
from .fork_executor import ForkExecutor, ForkPlan, ForkResult
from .hooks import HookEvent, HookRegistry, default_hook_registry
from .mcp_client import MCPClient, MCPTransport, default_mcp_manager
from .memory import MemoryLayer, default_memory
from .orchestrator_v2 import (
    ConversationOrchestrator,
    OrchestratorEvent,
    OrchestratorState,
    default_orchestrator,
)
from .permissions import (
    PermissionGate,
    PermissionMode,
    PermissionRule,
    default_permission_gate,
)
from .prompt_cache import PromptCacheManager, default_prompt_cache
from .safety_scanner import RiskLevel, ScanResult, scan_tool_call
from .skills_loader import Skill, SkillsLoader, default_skills
from .streaming_executor import StreamingToolExecutor
from .subagent import SubagentResult, SubagentRunner
from .tool_registry import ToolRegistry, ToolSpec, build_tool, default_registry

__all__ = [
    "ToolSpec",
    "build_tool",
    "ToolRegistry",
    "default_registry",
    "HookRegistry",
    "HookEvent",
    "default_hook_registry",
    "PermissionGate",
    "PermissionMode",
    "PermissionRule",
    "default_permission_gate",
    "ContextManager",
    "ContextSnapshot",
    "MemoryLayer",
    "default_memory",
    "SkillsLoader",
    "Skill",
    "default_skills",
    "MCPClient",
    "MCPTransport",
    "default_mcp_manager",
    "SubagentRunner",
    "SubagentResult",
    "ConversationOrchestrator",
    "OrchestratorEvent",
    "OrchestratorState",
    "default_orchestrator",
    "StreamingToolExecutor",
    "FeatureFlags",
    "ff",
    "RiskLevel",
    "ScanResult",
    "scan_tool_call",
    "PromptCacheManager",
    "default_prompt_cache",
    "ForkExecutor",
    "ForkPlan",
    "ForkResult",
]
