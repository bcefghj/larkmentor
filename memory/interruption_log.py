"""Interruption event logging for Analytics module."""

from dataclasses import dataclass
from typing import Dict, List

from utils.time_utils import now_ts, fmt_time


@dataclass
class InterruptionEvent:
    timestamp: int
    user_open_id: str
    sender: str
    chat_name: str
    level: str          # P0-P3
    action: str         # forwarded / queued / auto_replied / archived
    was_focusing: bool


_logs: Dict[str, List[InterruptionEvent]] = {}


def log_event(event: InterruptionEvent):
    uid = event.user_open_id
    if uid not in _logs:
        _logs[uid] = []
    _logs[uid].append(event)


def get_today_events(user_open_id: str) -> List[InterruptionEvent]:
    today_str = fmt_time()[:10]  # "YYYY-MM-DD"
    return [
        e for e in _logs.get(user_open_id, [])
        if fmt_time(None)[:10] == today_str  # simplified; works for same-day
    ]


def get_all_events(user_open_id: str) -> List[InterruptionEvent]:
    return _logs.get(user_open_id, [])


def clear_user_logs(user_open_id: str):
    _logs.pop(user_open_id, None)
