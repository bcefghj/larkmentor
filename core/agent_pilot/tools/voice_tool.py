"""voice.transcribe tool.

Three back-ends, tried in order:
    1. Doubao ASR (if ``ARK_ASR_MODEL`` is configured)
    2. Feishu Minutes API (for pre-recorded meetings)
    3. Demo fallback – returns a description or stub so demos still progress.

The tool signature is ``(audio_url=..., file_key=..., text=...)``. If the
caller already has text (e.g. IM text message) it's returned as-is.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

logger = logging.getLogger("pilot.tool.voice")


def voice_transcribe(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}

    if args.get("text"):
        return {"text": args["text"], "source": "inline"}

    audio_url = args.get("audio_url") or ""
    file_key = args.get("file_key") or ""
    file_path = args.get("file_path") or ""

    text = _try_doubao_asr(file_path or audio_url) or _try_feishu_minutes(file_key)
    if text:
        return {"text": text, "source": "asr"}

    fallback = _demo_transcription_fallback(file_path)
    if fallback:
        return {"text": fallback, "source": "demo_fallback"}

    return {
        "text": "（离线演示：语音转写未启用，返回占位文本）把本周讨论做成 PPT 并生成评审链接。",
        "source": "stub",
    }


def _try_doubao_asr(file_path: str) -> str:
    """Attempt ASR via available OpenAI-compatible provider (MiMo/ARK/MiniMax)."""
    if not file_path:
        return ""
    try:
        from config import Config
        from llm.llm_client import _select_provider

        api_key, base_url = _select_provider()
        if not api_key:
            return ""

        from openai import OpenAI
        asr_base_url = base_url.replace("/coding/v3", "/v3")
        client = OpenAI(api_key=api_key, base_url=asr_base_url)

        with open(file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="zh",
            )
        text = transcript.text if hasattr(transcript, "text") else str(transcript)
        if text and len(text.strip()) > 1:
            return text.strip()
    except Exception as e:
        logger.debug("ASR failed: %s", e)
    return ""


def _demo_transcription_fallback(file_path: str) -> str:
    """Demo fallback: return a description of what was received."""
    if not file_path or not os.path.exists(file_path):
        return ""
    size_kb = os.path.getsize(file_path) / 1024
    return f"[语音转文字] 收到 {size_kb:.0f}KB 音频文件，ASR 服务暂不可用，请以文字形式重新输入您的需求。"


def _try_feishu_minutes(file_key: str) -> str:
    """Try Feishu Minutes API for pre-recorded meeting transcription.

    ``file_key`` is treated as a ``minute_token`` when prefixed with ``minute_``
    or passed verbatim otherwise. Returns the flat transcript string.
    """
    if not file_key:
        return ""
    try:
        from core.feishu_advanced.minutes_fetch import fetch_minutes  # type: ignore

        r = fetch_minutes(file_key, need_speaker=True, need_timestamp=True) or {}
        if not r.get("ok"):
            return ""
        segs = r.get("segments") or []
        if segs:
            return "\n".join(
                f"[{s.get('speaker') or '?'} @ {int(s.get('ts_ms', 0)) // 1000}s] {s.get('text', '')}" for s in segs
            )
        return r.get("text", "")
    except Exception as e:
        logger.debug("feishu minutes skipped: %s", e)
        return ""
