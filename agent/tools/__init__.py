"""Unified Tool Registry · 把 Shield v3 / Mentor v4 / Feishu API 所有能力塌缩为 @tool。"""

from .registry import tool, get_registry, register_builtin_tools

# Import tool modules so decorators register themselves
from . import im_tools       # noqa: F401
from . import mentor_tools   # noqa: F401
from . import doc_tools      # noqa: F401
from . import canvas_tools   # noqa: F401
from . import slides_tools   # noqa: F401
from . import archive_tools  # noqa: F401
from . import memory_tools   # noqa: F401

register_builtin_tools()

__all__ = ["tool", "get_registry"]
