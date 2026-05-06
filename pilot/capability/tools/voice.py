"""voice.transcribe — 语音转写工具.

优先飞书 ASR API；无飞书 token 时返回 mock。
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("pilot.tool.voice")


def register_to(reg) -> None:
    reg.register(
        "voice.transcribe",
        description="把飞书语音消息转写为文本（飞书 ASR API）",
        input_schema={
            "type": "object",
            "properties": {
                "file_key": {"type": "string"},
                "message_id": {"type": "string"},
                "audio_url": {"type": "string"},
            },
        },
        read_only=True,
        namespace="pilot",
    )(voice_transcribe)


async def voice_transcribe(
    *,
    file_key: str = "",
    message_id: str = "",
    audio_url: str = "",
    _ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if file_key and message_id and os.getenv("FEISHU_APP_ID"):
        try:
            from pilot.surface.feishu.client import get_feishu_client

            client = get_feishu_client()
            text = await client.transcribe_audio(message_id=message_id, file_key=file_key)
            return {"text": text or "", "source": "feishu"}
        except Exception as e:
            logger.warning("voice.transcribe feishu failed: %s", e)

    return {"text": "", "source": "mock", "note": "未配置 ASR provider"}
