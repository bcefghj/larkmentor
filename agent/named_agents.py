"""Named Agents loader (ShanClaw 启发) · 从 .larkmentor/agents/*.yaml 加载。

每个 named agent 有独立 instruction / model / tools / permission / memory scope。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent.named_agents")


@dataclass
class NamedAgent:
    name: str
    role: str
    instruction: str
    model_kind: str = "default"
    tools: List[str] = field(default_factory=list)
    permission_mode: str = "default"
    memory_scope: str = "project"
    max_turns: int = 4


class NamedAgentRegistry:
    def __init__(self) -> None:
        self.agents: Dict[str, NamedAgent] = {}
        self._load()

    def _load(self) -> None:
        candidates = [
            Path.cwd() / ".larkmentor" / "agents",
            Path.home() / ".larkmentor" / "agents",
        ]
        for d in candidates:
            if not d.exists():
                continue
            for f in d.glob("*.yaml"):
                try:
                    import yaml  # type: ignore
                    data = yaml.safe_load(f.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        continue
                    agent = NamedAgent(
                        name=data.get("name", f.stem),
                        role=data.get("role", ""),
                        instruction=data.get("instruction", ""),
                        model_kind=data.get("model_kind", "default"),
                        tools=data.get("tools", []),
                        permission_mode=data.get("permission_mode", "default"),
                        memory_scope=data.get("memory_scope", "project"),
                        max_turns=int(data.get("max_turns", 4)),
                    )
                    self.agents[agent.name] = agent
                except ImportError:
                    logger.debug("yaml not installed, skipping %s", f)
                except Exception as e:
                    logger.warning("agent yaml load failed %s: %s", f, e)
        logger.info("NamedAgentRegistry: %d agents loaded", len(self.agents))

    def get(self, name: str) -> Optional[NamedAgent]:
        return self.agents.get(name)

    def list_names(self) -> List[str]:
        return list(self.agents.keys())

    def match_tools(self, tool_name: str) -> List[NamedAgent]:
        """Find agents that have access to this tool (supports glob)."""
        matches = []
        for a in self.agents.values():
            for t in a.tools:
                if t == tool_name:
                    matches.append(a); break
                if t.endswith(".*") and tool_name.startswith(t[:-2] + "."):
                    matches.append(a); break
        return matches


_singleton: Optional[NamedAgentRegistry] = None


def default_named_agents() -> NamedAgentRegistry:
    global _singleton
    if _singleton is None:
        _singleton = NamedAgentRegistry()
    return _singleton
