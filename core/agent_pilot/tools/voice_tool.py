"""voice.transcribe tool.

Three back-ends, tried in order:
    1. Doubao ASR (if ``ARK_ASR_MODEL`` is configured)
    2. Feishu Minutes API (for pre-recorded meetings)
    3. Offline stub – returns the raw file name so demos still progress.

The tool signature is ``(audio_url=..., file_key=..., text=...)``. If the
caller already has text (e.g. IM text message) it's returned as-is.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("pilot.tool.voice")


def voice_transcribe(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}

    if args.get("text"):
        return {"text": args["text"], "source": "inline"}

    audio_url = args.get("audio_url") or ""
    file_key = args.get("file_key") or ""

    text = _try_doubao(audio_url) or _try_feishu_minutes(file_key)
    if text:
        return {"text": text, "source": "asr"}

    return {
        "text": "（离线演示：语音转写未启用，返回占位文本）把本周讨论做成 PPT 并生成评审链接。",
        "source": "stub",
    }


def _try_doubao(audio_url: str) -> str:
    if not audio_url:
        return ""
    try:
        import os
        if not os.getenv("ARK_ASR_MODEL"):
            return ""
        # Placeholder: the Doubao ASR HTTP call
        return ""
    except Exception as e:
        logger.debug("doubao asr skipped: %s", e)
        return ""


def _try_feishu_minutes(file_key: str) -> str:
    if not file_key:
        return ""
    try:
        from core.feishu_advanced.minutes_fetch import fetch_minutes  # type: ignore
        r = fetch_minutes(file_key)
        return r.get("text", "")
    except Exception as e:
        logger.debug("feishu minutes skipped: %s", e)
        return ""
