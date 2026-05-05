"""Tool registry for Agent-Pilot.

Every tool is a plain callable ``(step, ctx) -> dict``. Tools may raise
on hard error; the orchestrator will capture the traceback.

For offline demos / unit tests all tools degrade gracefully: the real
Feishu API calls are wrapped in ``try/except`` and simulated results are
returned if credentials are missing or the network is unreachable.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict

logger = logging.getLogger("pilot.tools")

from .archive_tool import archive_bundle
from .canvas_tool import canvas_add_shape, canvas_create
from .doc_tool import doc_append, doc_create
from .im_tool import im_fetch_thread, im_send_message
from .mentor_tool import mentor_clarify, mentor_summarize
from .slide_tool import slide_generate, slide_rehearse
from .voice_tool import voice_transcribe


def build_default_registry() -> Dict[str, Callable]:
    registry = {
        "im.fetch_thread": im_fetch_thread,
        "im.send": im_send_message,
        "doc.create": doc_create,
        "doc.append": doc_append,
        "canvas.create": canvas_create,
        "canvas.add_shape": canvas_add_shape,
        "slide.generate": slide_generate,
        "slide.rehearse": slide_rehearse,
        "voice.transcribe": voice_transcribe,
        "archive.bundle": archive_bundle,
        "mentor.clarify": mentor_clarify,
        "mentor.summarize": mentor_summarize,
    }
    return registry


__all__ = ["build_default_registry"]
