"""Pull recent Feishu Minutes (妙记) transcripts into the Archival store."""

from __future__ import annotations

import logging
from typing import Dict, List

from core.flow_memory.archival import write_archival_summary

logger = logging.getLogger("flowguard.feishu.minutes")


def fetch_recent_minutes(open_id: str, *, limit: int = 5) -> List[Dict]:
    """Best-effort: list recent minutes the user can see, push to archival.

    Returns the list of records we successfully archived.
    """
    out: List[Dict] = []
    try:
        from bot.feishu_client import get_client
        from lark_oapi.api.minutes.v1 import (  # type: ignore
            ListMinuteRequest, GetMinuteTranscriptRequest,
        )
        client = get_client()
        req = ListMinuteRequest.builder().user_id_type("open_id").page_size(limit).build()
        resp = client.minutes.v1.minute.list(req)
        if not resp.success() or not resp.data or not getattr(resp.data, "items", None):
            return []
        for item in resp.data.items[:limit]:
            minute_token = getattr(item, "minute_token", None)
            title = getattr(item, "title", "") or "(无标题会议纪要)"
            if not minute_token:
                continue
            text = _fetch_transcript(client, minute_token)
            if not text:
                continue
            summary = f"## 会议：{title}\n\n{text[:1500]}"
            write_archival_summary(open_id, summary, kind="meeting",
                                   meta={"minute_token": minute_token})
            out.append({"minute_token": minute_token, "title": title, "chars": len(text)})
    except Exception as e:
        logger.debug("minutes fetch err: %s", e)
    return out


def _fetch_transcript(client, minute_token: str) -> str:
    try:
        from lark_oapi.api.minutes.v1 import GetMinuteTranscriptRequest  # type: ignore
        req = GetMinuteTranscriptRequest.builder().minute_token(minute_token).build()
        resp = client.minutes.v1.minute_transcript.get(req)
        if not resp.success() or not resp.data:
            return ""
        # Different SDK versions expose either ``content`` or ``transcript``.
        return getattr(resp.data, "content", "") or getattr(resp.data, "transcript", "") or ""
    except Exception:
        return ""
