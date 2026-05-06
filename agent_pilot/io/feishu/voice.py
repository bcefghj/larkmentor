"""Feishu 语音消息输入 – v13.

When a Feishu user sends an ``audio`` message, this module:
  1. downloads the .opus / .pcm via ``im.v1.message_resource.get``
  2. uploads to MiniMax / 豆包 ASR (whichever has API key configured)
  3. returns plain text for the event_router to process as a normal intent

The ASR call is best-effort: on failure the bot prompts the user to send
text instead. We keep the dependency surface small (just `requests`).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agent_pilot.io.feishu.voice")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
VOICE_CACHE = PROJECT_ROOT / "data" / "voice_cache"


def transcribe_feishu_audio(message_id: str, file_key: str, *, message_type: str = "audio") -> str:
    """Download a Feishu audio file and run ASR on it.

    Returns the transcribed text, or an empty string on failure.
    """
    audio_path = _download_audio(message_id, file_key, message_type=message_type)
    if not audio_path:
        return ""
    text = _run_asr(audio_path)
    return text or ""


# ── Download from Feishu ──────────────────────────────────────────────────────


def _download_audio(message_id: str, file_key: str, *, message_type: str) -> Optional[Path]:
    try:
        from bot.feishu_client import get_client
        from lark_oapi.api.im.v1 import GetMessageResourceRequest

        VOICE_CACHE.mkdir(parents=True, exist_ok=True)
        out_path = VOICE_CACHE / f"{message_id}_{file_key}.opus"

        if out_path.exists() and out_path.stat().st_size > 0:
            return out_path

        client = get_client()
        req = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(file_key)
            .type(message_type)
            .build()
        )
        resp = client.im.v1.message_resource.get(req)
        if not resp.success() or not resp.file:
            logger.warning("voice download failed code=%s msg=%s",
                           getattr(resp, "code", "?"), getattr(resp, "msg", "?"))
            return None
        with open(out_path, "wb") as f:
            # resp.file may be bytes or a file-like
            data = getattr(resp, "file", None)
            if hasattr(data, "read"):
                f.write(data.read())
            else:
                f.write(data or b"")
        if out_path.stat().st_size == 0:
            logger.warning("voice file empty: %s", out_path)
            return None
        return out_path
    except Exception as e:
        logger.warning("voice download exception: %s", e)
        return None


# ── ASR providers ────────────────────────────────────────────────────────────


def _run_asr(audio_path: Path) -> str:
    """Try MiniMax ASR → fail. Returns transcript or empty string."""
    # MiniMax ASR
    text = _minimax_asr(audio_path)
    if text:
        return text
    # 豆包 ASR (if ARK key present)
    text = _doubao_asr(audio_path)
    if text:
        return text
    logger.info("ASR: no provider succeeded")
    return ""


def _minimax_asr(audio_path: Path) -> str:
    api_key = os.getenv("MINIMAX_API_KEY", "")
    group_id = os.getenv("MINIMAX_GROUP_ID", "")
    if not api_key:
        return ""
    try:
        import requests
        url = f"https://api.minimax.chat/v1/speech_to_text"
        if group_id:
            url += f"?GroupId={group_id}"
        with open(audio_path, "rb") as f:
            files = {"file": (audio_path.name, f, "audio/opus")}
            data = {"model": "speech-01", "language": "zh"}
            headers = {"Authorization": f"Bearer {api_key}"}
            r = requests.post(url, headers=headers, files=files, data=data, timeout=60)
        r.raise_for_status()
        j = r.json()
        text = (j.get("text") or j.get("result", {}).get("text") or "").strip()
        if text:
            logger.info("MiniMax ASR success: %d chars", len(text))
        return text
    except Exception as e:
        logger.debug("MiniMax ASR failed: %s", e)
        return ""


def _doubao_asr(audio_path: Path) -> str:
    api_key = os.getenv("ARK_API_KEY", "")
    if not api_key:
        return ""
    # 火山方舟 ASR API placeholder - use OpenAI compatible endpoint if exists
    try:
        import requests
        # Doubao TTS/ASR API: this is a placeholder for the actual endpoint
        # which differs by region/account. We try the most common path.
        url = "https://ark.cn-beijing.volces.com/api/v3/audio/transcriptions"
        with open(audio_path, "rb") as f:
            files = {"file": (audio_path.name, f, "audio/opus")}
            data = {"model": "doubao-asr"}
            headers = {"Authorization": f"Bearer {api_key}"}
            r = requests.post(url, headers=headers, files=files, data=data, timeout=60)
        if r.status_code == 200:
            j = r.json()
            return (j.get("text") or "").strip()
    except Exception as e:
        logger.debug("Doubao ASR failed: %s", e)
    return ""


__all__ = ["transcribe_feishu_audio"]
