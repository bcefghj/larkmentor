"""Agent-Pilot v13 tools – canonical implementations.

These replace the old ``core/agent_pilot/tools/*_tool.py`` modules. The
old module names continue to work as compat re-exports.
"""

from agent_pilot.tools.doc import doc_append, doc_create  # noqa: F401
from agent_pilot.tools.canvas import canvas_add_shape, canvas_create  # noqa: F401
from agent_pilot.tools.slide import slide_generate, slide_rehearse  # noqa: F401

__all__ = [
    "doc_create",
    "doc_append",
    "canvas_create",
    "canvas_add_shape",
    "slide_generate",
    "slide_rehearse",
]
