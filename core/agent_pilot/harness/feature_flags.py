"""Lightweight feature flags for Agent-Pilot.

Flags can be set via:
1. Environment variables: AGENT_PILOT_FF_<FLAG_NAME>=true|false
2. JSON file: data/feature_flags.json
3. Runtime API: FeatureFlags.set("flag_name", True)

Environment variables take highest precedence.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("pilot.harness.feature_flags")

_FLAGS_FILE = Path(__file__).resolve().parent.parent.parent.parent / "data" / "feature_flags.json"


class FeatureFlags:
    _instance: Optional["FeatureFlags"] = None

    def __init__(self) -> None:
        self._runtime: Dict[str, bool] = {}
        self._file_cache: Dict[str, bool] = {}
        self._load_file()

    @classmethod
    def instance(cls) -> "FeatureFlags":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_file(self) -> None:
        try:
            if _FLAGS_FILE.exists():
                self._file_cache = json.loads(_FLAGS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug("feature flags file load failed: %s", e)

    def enabled(self, flag: str, default: bool = False) -> bool:
        env_key = f"AGENT_PILOT_FF_{flag.upper().replace('.', '_')}"
        env_val = os.getenv(env_key)
        if env_val is not None:
            return env_val.lower() in ("1", "true", "yes", "on")
        if flag in self._runtime:
            return self._runtime[flag]
        return self._file_cache.get(flag, default)

    def set(self, flag: str, value: bool) -> None:
        self._runtime[flag] = value

    def all_flags(self) -> Dict[str, bool]:
        merged = dict(self._file_cache)
        merged.update(self._runtime)
        return merged

    def save(self) -> None:
        try:
            _FLAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            merged = self.all_flags()
            _FLAGS_FILE.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug("feature flags save failed: %s", e)


def ff(flag: str, default: bool = False) -> bool:
    return FeatureFlags.instance().enabled(flag, default)


DEMO_MODE = "demo_mode"
STRUCTURED_TOOL_CALLING = "structured_tool_calling"
VOICE_ASR_ENABLED = "voice_asr_enabled"
FEISHU_API_ENABLED = "feishu_api_enabled"
CRDT_REDIS_BACKEND = "crdt_redis_backend"
ADVANCED_PLANNING = "advanced_planning"
