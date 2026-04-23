"""Offline merge strategy helpers (Scenario E / good-to-have offline support).

Yjs CRDTs already guarantee convergence, but we still expose two
utilities:

* ``record_offline_update(room, update_b64)`` – append an update coming
  from a client that was offline, so we can audit merge history.
* ``reconcile(room)`` – compute a deterministic diff summary after
  re-syncing so the dashboard can show "merged N offline edits".
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List

logger = logging.getLogger("pilot.sync.offline")

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "pilot_offline",
)


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def record_offline_update(room: str, update_b64: str, client_id: str = "") -> None:
    _ensure_dir()
    path = os.path.join(DATA_DIR, f"{room}.log.jsonl")
    entry = {
        "ts": int(time.time()),
        "client_id": client_id,
        "update_b64_len": len(update_b64),
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.debug("record_offline_update skipped: %s", e)


def reconcile(room: str) -> Dict[str, Any]:
    _ensure_dir()
    path = os.path.join(DATA_DIR, f"{room}.log.jsonl")
    entries: List[Dict[str, Any]] = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        continue
        except Exception as e:
            logger.debug("reconcile read failed: %s", e)
    return {
        "room": room,
        "offline_updates": len(entries),
        "by_client": _count_by(entries, "client_id"),
    }


def _count_by(entries: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for e in entries:
        k = e.get(key, "") or "unknown"
        out[k] = out.get(k, 0) + 1
    return out
