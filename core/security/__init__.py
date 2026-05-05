"""Agent-Pilot 8-layer security stack.

Inspired by Anthropic Claude Code's seven-gate pipeline. Layers (in order):

    1. PermissionManager   – capability-based 5-tier permission gate
    2. TranscriptClassifier – LLM-as-judge prompt-injection detector
    3. HookSystem          – Pre/Post lifecycle hooks for org overrides
    4. PIIScrubber         – regex-based PII redaction before LLM call
    5. KeywordDenylist     – fast deny for high-risk content patterns
    6. RateLimiter         – per-user / per-tool rate caps
    7. ToolSandbox         – allow-list of Feishu API surfaces a tool can hit
    8. AuditLog            – append-only JSONL trace for compliance / replay

The modules are intentionally small and composable so the security pipeline
can be reordered or mocked in tests.
"""

from .audit_log import AuditEntry, audit, query_audit  # noqa: F401
from .hook_system import HookEvent, HookSystem  # noqa: F401
from .keyword_denylist import (  # noqa: F401
    DenyHit,
    KeywordDenylist,
    default_denylist,
)
from .keyword_denylist import (
    check_text as denylist_check,
)
from .permission_manager import PermissionLevel, PermissionManager  # noqa: F401
from .pii_scrubber import PIIReport, scrub_pii  # noqa: F401
from .rate_limiter import (  # noqa: F401
    RateDecision,
    RateLimiter,
    default_limiter,
)
from .rate_limiter import (
    acquire as ratelimit_acquire,
)
from .tool_sandbox import (  # noqa: F401
    SandboxDecision,
    SandboxProfile,
    ToolSandbox,
    default_sandbox,
)
from .tool_sandbox import (
    check as sandbox_check,
)
from .transcript_classifier import InjectionVerdict, classify_transcript  # noqa: F401
