"""Sender Profile – per-sender behavior memory and identity classification.

This module is part of FlowGuard's 6-dimension classifier. It maintains a
persistent profile per sender (open_id) capturing:

- identity_tag : VIP / superior / peer / unknown / bot
- relation_strength : 0.0 - 1.0 (frequency-based)
- recent_messages_count : how many times this sender messaged in last 7 days
- avg_response_delay_sec : how fast the user actually responds → reverse signal
- last_seen_ts
- is_in_whitelist : computed at lookup time

The profile is updated continuously from incoming events and from user feedback
(e.g. when user replies quickly to a message classified as P2, we lower the
sender's "ignorability" weight next time).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional

from utils.time_utils import now_ts

logger = logging.getLogger("flowguard.sender_profile")

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)
PROFILE_FILE = os.path.join(DATA_DIR, "sender_profiles.json")

# ── Identity tags ──
IDENTITY_VIP = "vip"               # explicitly marked
IDENTITY_SUPERIOR = "superior"     # leader/manager
IDENTITY_PEER = "peer"             # frequent collaborator
IDENTITY_OCCASIONAL = "occasional"  # infrequent contact
IDENTITY_UNKNOWN = "unknown"       # never seen
IDENTITY_BOT = "bot"               # automated sender

IDENTITY_SCORE = {
    IDENTITY_VIP: 1.0,
    IDENTITY_SUPERIOR: 0.85,
    IDENTITY_PEER: 0.50,
    IDENTITY_OCCASIONAL: 0.25,
    IDENTITY_UNKNOWN: 0.30,
    IDENTITY_BOT: 0.05,
}


@dataclass
class SenderProfile:
    sender_id: str
    name: str = ""
    identity_tag: str = IDENTITY_UNKNOWN
    recent_messages_count: int = 0       # rolling 7-day count
    total_messages_count: int = 0
    last_seen_ts: int = 0
    user_response_delays: List[int] = field(default_factory=list)  # seconds
    user_marked_important: int = 0        # times user replied within 60s
    user_marked_unimportant: int = 0      # times user ignored / archived

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SenderProfile":
        return cls(
            sender_id=d.get("sender_id", ""),
            name=d.get("name", ""),
            identity_tag=d.get("identity_tag", IDENTITY_UNKNOWN),
            recent_messages_count=d.get("recent_messages_count", 0),
            total_messages_count=d.get("total_messages_count", 0),
            last_seen_ts=d.get("last_seen_ts", 0),
            user_response_delays=d.get("user_response_delays", []),
            user_marked_important=d.get("user_marked_important", 0),
            user_marked_unimportant=d.get("user_marked_unimportant", 0),
        )

    def relation_strength(self) -> float:
        """Compute 0-1 relation strength from message frequency.

        - 0  recent messages → 0.0
        - 5+ recent messages → 0.5
        - 20+ recent messages → 1.0 (capped)
        """
        n = self.recent_messages_count
        if n >= 20:
            return 1.0
        if n >= 5:
            return 0.5 + (n - 5) / 30.0
        return n / 10.0  # 0..0.5

    def identity_score(self) -> float:
        return IDENTITY_SCORE.get(self.identity_tag, 0.3)

    def avg_response_delay_sec(self) -> float:
        """User's average response delay to this sender. Lower = more important."""
        if not self.user_response_delays:
            return -1.0
        return sum(self.user_response_delays) / len(self.user_response_delays)

    def importance_bias(self) -> float:
        """Reverse signal: how often user actually treats this sender as important.

        Returns -0.2..+0.2 to nudge the final score.
        """
        total = self.user_marked_important + self.user_marked_unimportant
        if total < 3:
            return 0.0
        ratio = self.user_marked_important / total
        return (ratio - 0.5) * 0.4  # -0.2 .. +0.2


# ── In-memory store ──
_profiles: Dict[str, SenderProfile] = {}


def get_profile(sender_id: str, name: str = "") -> SenderProfile:
    if sender_id not in _profiles:
        _profiles[sender_id] = SenderProfile(sender_id=sender_id, name=name)
    p = _profiles[sender_id]
    if name and not p.name:
        p.name = name
    return p


def all_profiles() -> List[SenderProfile]:
    return list(_profiles.values())


def record_incoming(sender_id: str, name: str = "") -> SenderProfile:
    """Record that this sender sent a message right now."""
    p = get_profile(sender_id, name)
    p.recent_messages_count += 1
    p.total_messages_count += 1
    p.last_seen_ts = now_ts()

    # Auto-promote: 5+ recent messages → peer; 20+ → superior candidate
    if p.identity_tag == IDENTITY_UNKNOWN and p.recent_messages_count >= 3:
        p.identity_tag = IDENTITY_OCCASIONAL
    if p.identity_tag == IDENTITY_OCCASIONAL and p.recent_messages_count >= 5:
        p.identity_tag = IDENTITY_PEER
    save()
    return p


def record_user_response(sender_id: str, delay_sec: int):
    """Record how fast the user actually responded to a sender's message.

    Called from event handler when user types a reply within a tracked window.
    """
    p = get_profile(sender_id)
    p.user_response_delays.append(delay_sec)
    if len(p.user_response_delays) > 50:
        p.user_response_delays = p.user_response_delays[-50:]
    if delay_sec <= 60:
        p.user_marked_important += 1
    elif delay_sec >= 1800:
        p.user_marked_unimportant += 1
    save()


def mark_identity(sender_id: str, tag: str):
    p = get_profile(sender_id)
    p.identity_tag = tag
    save()


def decay_recent_counts():
    """Periodic rolling-window decay (call once per day from scheduler)."""
    for p in _profiles.values():
        p.recent_messages_count = max(0, int(p.recent_messages_count * 0.8))
    save()


# ── Persistence ──

def save():
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        data = {sid: p.to_dict() for sid, p in _profiles.items()}
        with open(PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Failed to save sender profiles: %s", e)


def load():
    if not os.path.exists(PROFILE_FILE):
        return
    try:
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for sid, d in data.items():
            _profiles[sid] = SenderProfile.from_dict(d)
        logger.info("Loaded %d sender profiles", len(_profiles))
    except Exception as e:
        logger.error("Failed to load sender profiles: %s", e)
