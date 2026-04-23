"""LarkMentor v4 · Unified Agent Harness

对标 Claude Code (51 万行) / Shannon (Kocoro-lab, 1.6K stars) / Hermes (Nous, 109K stars)。

核心设计：
- 9 步 pipeline（对齐 Claude Code queryLoop）
- 5 层 context 压缩（budget/snip/microcompact/collapse/autocompact）
- 4 层 CLAUDE.md 记忆继承（Enterprise/Project/User/Local）+ Auto Memory
- 7 层安全栈（Permission/Classifier/Hook/ToolSafety/FS/Secret/Sandbox）
- 6 hooks 生命周期
- 3 层 Skills 渐进披露
- MCP 双通道（stdio + HTTP）
- Subagent sidechain transcript
- Orchestrator-Worker (Anthropic 90.2%)
- Builder-Validator 分离 + Citation Agent
- 8 种执行策略 + 5 种推理模式（Shannon）
- Multi-provider routing（豆包/MiniMax M2.7/DeepSeek/Kimi）

理念：1.6% AI + 98.4% harness（对标 Claude Code）。
"""

__version__ = "4.0.0"

from .loop import AgentLoop, default_loop
from .context import ContextManager, default_context_manager
from .permissions import PermissionGate, PermissionMode, default_permission_gate
from .hooks import HookRegistry, HookEvent, default_hook_registry
from .memory import MemoryLayer, default_memory
from .skills import SkillsLoader, default_skills_loader
from .mcp import MCPManager, default_mcp_manager
from .subagent import SubagentRunner, default_subagent_runner

__all__ = [
    "AgentLoop", "default_loop",
    "ContextManager", "default_context_manager",
    "PermissionGate", "PermissionMode", "default_permission_gate",
    "HookRegistry", "HookEvent", "default_hook_registry",
    "MemoryLayer", "default_memory",
    "SkillsLoader", "default_skills_loader",
    "MCPManager", "default_mcp_manager",
    "SubagentRunner", "default_subagent_runner",
]
