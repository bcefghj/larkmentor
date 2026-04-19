"""LarkMentor Runtime · Claude Code 7 支柱内层

Borrowed from Anthropic Claude Code's runtime architecture, adapted to the
Feishu IM协同助手 domain.

Public API:
- ToolRegistry / ToolMetadata: register and invoke tools with built-in
  permission/audit/rate-limit enforcement
- HookRuntime: lifecycle hook facade (PRE_*/POST_*) backed by
  core.security.hook_system
- SkillLoader / SkillManifest: pluggable skill loading
- PermissionFacade: thin facade over core.security.permission_manager

These four facades enforce the architecture invariant declared in
ARCHITECTURE.md §2 Principle 1: "all domain calls must go through the
runtime layer". No direct LLM/Feishu API calls in domain code.
"""

from .tool_registry import ToolRegistry, ToolMetadata, default_registry  # noqa: F401
from .hook_runtime import HookRuntime, default_hook_runtime  # noqa: F401
from .skill_loader import (  # noqa: F401
    SkillLoader,
    SkillManifest,
    default_loader,
)
from .permission_facade import PermissionFacade, default_facade  # noqa: F401
