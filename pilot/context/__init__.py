"""Context 层 — append-only 事件日志 + ContextPack + filesystem working memory + AGENTS.md cascade.

设计原则:
  - append-only：所有事件不可变，便于 replay / debug / audit
  - filesystem as working memory：大段内容落盘后用 ArtifactRef 引用
  - cache stability：system prompt 用 SYSTEM_PROMPT_DYNAMIC_BOUNDARY 分两段
"""

from pilot.context.event_log import EventLog  # noqa: F401
from pilot.context.context_pack import ContextPack, ContextPackBuilder  # noqa: F401
from pilot.context.filesystem_memory import FilesystemMemory  # noqa: F401
from pilot.context.agents_md import discover_agents_md, load_cascade  # noqa: F401
from pilot.context.prompt_assembler import PromptAssembler, SYSTEM_PROMPT_DYNAMIC_BOUNDARY  # noqa: F401

__all__ = [
    "EventLog",
    "ContextPack",
    "ContextPackBuilder",
    "FilesystemMemory",
    "discover_agents_md",
    "load_cascade",
    "PromptAssembler",
    "SYSTEM_PROMPT_DYNAMIC_BOUNDARY",
]
