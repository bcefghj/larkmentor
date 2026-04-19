"""FlowMemory: a three-tier long-term memory engine for the FlowGuard agent.

Inspired by Anthropic Claude Code's wU2 compaction pipeline and the 6-tier
CLAUDE.md memory system. Designed for the OpenClaw track-2 brief
"Enterprise long-program collaboration Memory system".

Layers
------

* ``working``      – per-session sliding window (~100 events).
* ``compaction``   – periodic summary (per focus session / per week / per
                     meeting) compressed to ~600 tokens of markdown.
* ``archival``     – durable artifacts written to Feishu Bitable, docx and
                     Wiki for cross-session, cross-user retrieval.

Plus the ``flow_memory_md`` module that resolves a six-level
``flow_memory.md`` hierarchy (Enterprise / Workspace / Department / Group /
User / Session) at request time.
"""

from .working import WorkingMemory, WorkingEvent  # noqa: F401
from .compaction import compact_session, CompactionResult  # noqa: F401
from .archival import write_archival_summary, query_archival  # noqa: F401
from .flow_memory_md import resolve_memory_md  # noqa: F401
