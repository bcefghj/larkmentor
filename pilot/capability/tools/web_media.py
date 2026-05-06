"""V1.5 — web.search 与 media.tts 工具注册.

设计取舍:
  - 不实现 image / video / voice_clone / image_understand。这些 fast 时期挂了空壳，
    没有真正可调通的下游 API；不做"假工具"。
  - web.search 委托 pilot.llm.web_search.WebSearcher（DDG + Bing CN），不联 LLM。
  - media.tts 走 MiniMax T2A（/v1/t2a_v2）。默认禁用（AGENT_PILOT_ENABLE_TTS=0），
    避免比赛环境意外消耗配额。
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from pilot.context.filesystem_memory import ARTIFACTS_DIR

logger = logging.getLogger("pilot.tool.web_media")


def register_to(reg) -> None:
    reg.register(
        "web.search",
        description="联网搜索（DuckDuckGo HTML 主路径 + Bing CN 兜底，无需 API key）",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "k": {"type": "integer", "description": "返回前 k 条，默认 5", "default": 5},
            },
            "required": ["query"],
        },
        read_only=True,
        namespace="pilot",
    )(web_search)

    reg.register(
        "media.tts",
        description="文本转语音（MiniMax T2A）。默认禁用，AGENT_PILOT_ENABLE_TTS=1 才生效",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要合成的文本"},
                "voice": {"type": "string", "description": "voice_id，默认 male-qn-qingse", "default": "male-qn-qingse"},
                "speed": {"type": "number", "description": "0.5-2.0", "default": 1.0},
            },
            "required": ["text"],
        },
        read_only=False,
        namespace="pilot",
    )(media_tts)


async def web_search(*, query: str, k: int = 5, _ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """调用 WebSearcher 抓 DDG/Bing 并返回 [{title,url,snippet}] 数组."""
    from pilot.llm.web_search import default_searcher

    started = time.monotonic()
    try:
        results = await default_searcher().search(query, k=k)
    except Exception as e:
        logger.warning("web.search failed: %s", e)
        return {"ok": False, "query": query, "results": [], "error": str(e)[:200]}

    elapsed_ms = int((time.monotonic() - started) * 1000)
    return {
        "ok": True,
        "query": query,
        "k": k,
        "results": results,
        "count": len(results),
        "elapsed_ms": elapsed_ms,
    }


async def media_tts(
    *,
    text: str,
    voice: str = "male-qn-qingse",
    speed: float = 1.0,
    _ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """文本转 mp3，落盘到 artifacts/tts/<id>.mp3 并返回相对 URL.

    默认禁用，env AGENT_PILOT_ENABLE_TTS=1 才会真调 MiniMax T2A。
    """
    if os.getenv("AGENT_PILOT_ENABLE_TTS", "0") != "1":
        return {"ok": False, "reason": "tts_disabled", "hint": "AGENT_PILOT_ENABLE_TTS=1 才启用"}
    if not text.strip():
        return {"ok": False, "reason": "empty_text"}

    api_key = os.getenv("MINIMAX_API_KEY", "")
    group_id = os.getenv("MINIMAX_GROUP_ID", "")
    if not api_key or not group_id:
        return {"ok": False, "reason": "minimax_credentials_missing"}

    aid = f"tts_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    out_dir: Path = ARTIFACTS_DIR / "tts"
    out_dir.mkdir(parents=True, exist_ok=True)
    mp3_path = out_dir / f"{aid}.mp3"

    url = f"https://api.minimaxi.com/v1/t2a_v2?GroupId={group_id}"
    body = {
        "model": "speech-02-hd",
        "text": text[:2000],
        "voice_setting": {"voice_id": voice, "speed": float(speed), "vol": 1.0, "pitch": 0},
        "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3"},
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as cli:
            r = await cli.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
        audio_hex = (data.get("data") or {}).get("audio") or ""
        if not audio_hex:
            return {"ok": False, "reason": "minimax_empty_audio", "raw": data}
        mp3_path.write_bytes(bytes.fromhex(audio_hex))
    except Exception as e:
        logger.warning("media.tts failed: %s", e)
        return {"ok": False, "reason": "tts_request_failed", "error": str(e)[:200]}

    base = (os.getenv("DASHBOARD_PUBLIC_BASE") or "").rstrip("/")
    rel = f"/artifacts/tts/{mp3_path.name}"
    return {
        "ok": True,
        "tts_id": aid,
        "mp3_path": str(mp3_path),
        "mp3_url": rel,
        "mp3_url_absolute": f"{base}{rel}" if base else rel,
        "size_bytes": mp3_path.stat().st_size if mp3_path.exists() else 0,
    }
