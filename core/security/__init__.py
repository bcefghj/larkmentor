"""LarkMentor 8-layer security stack.

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

from .permission_manager import PermissionManager, PermissionLevel  # noqa: F401
from .transcript_classifier import classify_transcript, InjectionVerdict  # noqa: F401
from .hook_system import HookSystem, HookEvent  # noqa: F401
from .pii_scrubber import scrub_pii, PIIReport  # noqa: F401
from .audit_log import audit, query_audit, AuditEntry  # noqa: F401
from .keyword_denylist import (  # noqa: F401
    KeywordDenylist, DenyHit,
    default_denylist, check_text as denylist_check,
)
from .rate_limiter import (  # noqa: F401
    RateLimiter, RateDecision,
    default_limiter, acquire as ratelimit_acquire,
)
from .tool_sandbox import (  # noqa: F401
    ToolSandbox, SandboxProfile, SandboxDecision,
    default_sandbox, check as sandbox_check,
)
