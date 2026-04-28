"""LarkMentor v1 · My Mentor Stats API.

Returns per-user stats for the dashboard:
- this week's mentor invocations by kind
- minutes saved (heuristic: 23 min × proactive fires)
- onboarding status
- last 5 mentor entries (preview)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List

logger = logging.getLogger("flowguard.dashboard.mentor_stats")


@dataclass
class MentorStats:
    open_id: str
    range_days: int = 7
    invocations: Dict[str, int] = field(default_factory=dict)
    proactive_fires: int = 0
    minutes_saved_estimate: int = 0
    onboarding_completed: bool = False
    onboarding_progress: str = "0/5"
    recent_entries: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "open_id": self.open_id,
            "range_days": self.range_days,
            "invocations": self.invocations,
            "proactive_fires": self.proactive_fires,
            "minutes_saved_estimate": self.minutes_saved_estimate,
            "onboarding_completed": self.onboarding_completed,
            "onboarding_progress": self.onboarding_progress,
            "recent_entries": self.recent_entries,
        }


# Each Mark-2008 interruption recovery is ~23 minutes. Proactive draft saves
# the user from full context-switch (we estimate 8 min saved per fire on
# average; 23 min is the upper bound when the user otherwise had to fully
# disengage to reply).
_MIN_SAVED_PER_FIRE = 8


def compute(open_id: str, range_days: int = 7) -> MentorStats:
    """Compute MentorStats for a user. Always returns; never raises."""
    stats = MentorStats(open_id=open_id, range_days=range_days)

    cutoff = int(time.time()) - range_days * 86400

    try:
        from core.mentor.growth_doc import load_entries

        entries = load_entries(open_id, since_ts=cutoff)
        kinds: Dict[str, int] = {}
        for e in entries:
            kinds[e.kind] = kinds.get(e.kind, 0) + 1
        stats.invocations = kinds
        stats.proactive_fires = kinds.get("proactive_picked", 0)
        stats.minutes_saved_estimate = stats.proactive_fires * _MIN_SAVED_PER_FIRE
        stats.recent_entries = [
            {
                "ts": e.ts,
                "kind": e.kind,
                "original": (e.original or "")[:80],
                "improved": (e.improved or "")[:80],
                "citations": e.citations,
            }
            for e in entries[-5:]
        ]
    except Exception as e:
        logger.debug("mentor_stats_growth_fail err=%s", e)

    try:
        from core.mentor.mentor_onboard import get_session

        sess = get_session(open_id)
        if sess is not None:
            stats.onboarding_completed = sess.completed
            stats.onboarding_progress = sess.progress
    except Exception as e:
        logger.debug("mentor_stats_onboard_fail err=%s", e)

    return stats


def register(app) -> None:
    """Mount /api/v4/mentor_stats route on a FastAPI app."""
    try:
        from fastapi import Query
        from fastapi.responses import JSONResponse
    except Exception:  # noqa: BLE001
        return

    @app.get("/api/v4/mentor_stats")
    async def _mentor_stats(open_id: str = Query(..., min_length=4),
                            range_days: int = Query(7, ge=1, le=90)):
        try:
            return compute(open_id, range_days=range_days).to_dict()
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": str(e)}, status_code=500)
