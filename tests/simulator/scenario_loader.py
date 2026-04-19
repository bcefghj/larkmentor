"""Scenario loader: parse YAML scenario files into Python dicts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

try:
    import yaml
except ImportError:
    yaml = None

SCENARIO_DIR = Path(__file__).parent / "scenarios"


def load_all_scenarios() -> List[Dict]:
    if yaml is None:
        raise RuntimeError("PyYAML not installed. Run: pip install pyyaml")
    scenarios: List[Dict] = []
    for path in sorted(SCENARIO_DIR.glob("*.yaml")):
        with open(path, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        if not doc:
            continue
        if isinstance(doc, list):
            for s in doc:
                s["__source__"] = path.name
                scenarios.append(s)
        elif isinstance(doc, dict) and "scenarios" in doc:
            for s in doc["scenarios"]:
                s["__source__"] = path.name
                scenarios.append(s)
    return scenarios


def filter_scenarios(scenarios: List[Dict], category: str = None) -> List[Dict]:
    if not category:
        return scenarios
    return [s for s in scenarios if s.get("category") == category]
