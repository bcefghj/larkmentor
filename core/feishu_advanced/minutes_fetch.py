"""Pull recent Feishu Minutes (妙记) transcripts into the Archival store.

P1.3 / P2.8 upgrade: exposes both batch discovery (``fetch_recent_minutes``)
and single-token fetch with speaker + timestamp (``fetch_minutes``) that
voice.transcribe / Pilot planner use.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

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


def fetch_minutes(
    minute_token: str,
    *,
    need_speaker: bool = True,
    need_timestamp: bool = True,
) -> Dict:
    """Single-minute fetch with optional speaker / timestamp columns.

    Returns a dict::

        {
          "minute_token": "...",
          "title": "...",
          "text": "plain transcript",
          "segments": [
            {"speaker": "...", "ts_ms": 1234, "text": "..."},
            ...
          ],
          "ok": True,
        }

    ``text`` is always filled (best-effort). ``segments`` is empty when the
    SDK or the minute doesn't expose speaker diarisation.
    """
    out: Dict = {
        "minute_token": minute_token, "title": "", "text": "",
        "segments": [], "ok": False,
    }
    if not minute_token:
        return out
    try:
        from bot.feishu_client import get_client
        client = get_client()
        out["text"] = _fetch_transcript(client, minute_token)
        if not out["text"]:
            return out
        out["ok"] = True
        if need_speaker or need_timestamp:
            out["segments"] = _fetch_segments(client, minute_token,
                                              need_speaker=need_speaker,
                                              need_timestamp=need_timestamp)
        # Try to pull title.
        try:
            from lark_oapi.api.minutes.v1 import GetMinuteRequest  # type: ignore
            mreq = GetMinuteRequest.builder().minute_token(minute_token).build()
            mresp = client.minutes.v1.minute.get(mreq)
            if getattr(mresp, "success", lambda: False)() and getattr(mresp, "data", None):
                out["title"] = getattr(mresp.data, "title", "") or ""
        except Exception:
            pass
        return out
    except Exception as exc:
        logger.debug("fetch_minutes failed: %s", exc)
        return out


def _fetch_segments(client, minute_token: str, *,
                    need_speaker: bool, need_timestamp: bool) -> List[Dict]:
    """Return [{speaker, ts_ms, text}, ...]. Empty on failure."""
    try:
        from lark_oapi.api.minutes.v1 import GetMinuteTranscriptRequest  # type: ignore
        builder = GetMinuteTranscriptRequest.builder().minute_token(minute_token)
        # Some SDK versions expose need_speaker / need_timestamp params.
        try:
            builder = builder.need_speaker(need_speaker).need_timestamp(need_timestamp)
        except Exception:
            pass
        req = builder.build()
        resp = client.minutes.v1.minute_transcript.get(req)
        if not resp.success() or not resp.data:
            return []
        data = resp.data
        segments = getattr(data, "segments", None) or getattr(data, "items", None) or []
        out: List[Dict] = []
        for seg in segments:
            out.append({
                "speaker": getattr(seg, "speaker_name", "") or getattr(seg, "speaker", ""),
                "ts_ms": int(getattr(seg, "start_time", 0) or getattr(seg, "ts_ms", 0) or 0),
                "text": getattr(seg, "content", "") or getattr(seg, "text", ""),
            })
        return out
    except Exception as exc:
        logger.debug("minute segments fetch: %s", exc)
        return []
