"""SkillLoader · 可插拔 Skill 加载器 (Claude Code 支柱 3)

A "Skill" in LarkMentor is a bundle of:
- one ``SkillManifest`` (name / version / triggers / tools / system_prompt)
- one or more tools registered to ``ToolRegistry``
- (optional) hooks registered to ``HookRuntime``

Mentor 4 大功能（write / task / review / onboard）以及未来用户自定义的
任何 Skill 都通过 SkillManifest 描述，统一加载。

设计目的（ARCHITECTURE.md §1 支柱 3）：
- 让 mentor 模块可拔插（用户可禁用某个 Skill）
- 让外部开发者可以贡献 Skill 包（v2 roadmap）
- 让 MCP `skill_invoke` tool 有统一调用入口
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("larkmentor.runtime.skill_loader")


@dataclass
class SkillManifest:
    """一个 Skill 的元数据"""

    name: str
    version: str = "1.0.0"
    description: str = ""
    tools: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)
    system_prompt: str = ""
    enabled: bool = True
    permission: str = "DRAFT_ACTION"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "tools": list(self.tools),
            "triggers": list(self.triggers),
            "system_prompt": self.system_prompt,
            "enabled": self.enabled,
            "permission": self.permission,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SkillManifest":
        return cls(
            name=d["name"],
            version=d.get("version", "1.0.0"),
            description=d.get("description", ""),
            tools=list(d.get("tools", [])),
            triggers=list(d.get("triggers", [])),
            system_prompt=d.get("system_prompt", ""),
            enabled=d.get("enabled", True),
            permission=d.get("permission", "DRAFT_ACTION"),
            metadata=dict(d.get("metadata", {})),
        )


class SkillLoader:
    """Skill 注册中心 + 触发匹配"""

    def __init__(self) -> None:
        self._skills: Dict[str, SkillManifest] = {}

    # ── Loading ──────────────────────────────────────────────

    def register(self, manifest: SkillManifest) -> None:
        if manifest.name in self._skills:
            logger.warning("skill re-registered: %s", manifest.name)
        self._skills[manifest.name] = manifest
        logger.info(
            "skill registered: %s v%s [%d tools, %d triggers]",
            manifest.name, manifest.version,
            len(manifest.tools), len(manifest.triggers),
        )

    def load_from_dict(self, d: Dict[str, Any]) -> SkillManifest:
        m = SkillManifest.from_dict(d)
        self.register(m)
        return m

    def load_from_json_file(self, path: Path) -> Optional[SkillManifest]:
        if not path.exists():
            return None
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            return self.load_from_dict(d)
        except Exception as e:
            logger.warning("skill json load failed (%s): %s", path, e)
            return None

    def load_dir(self, dir_path: Path) -> int:
        if not dir_path.exists():
            return 0
        loaded = 0
        for f in sorted(dir_path.glob("*.json")):
            if self.load_from_json_file(f):
                loaded += 1
        logger.info("loaded %d skills from %s", loaded, dir_path)
        return loaded

    # ── Query ────────────────────────────────────────────────

    def list_skills(self, only_enabled: bool = True) -> List[SkillManifest]:
        if only_enabled:
            return [s for s in self._skills.values() if s.enabled]
        return list(self._skills.values())

    def get(self, name: str) -> Optional[SkillManifest]:
        return self._skills.get(name)

    def find_for_command(self, text: str) -> Optional[SkillManifest]:
        """Find the first enabled skill whose triggers match the text."""
        text_lower = text.lower()
        for skill in self._skills.values():
            if not skill.enabled:
                continue
            for trig in skill.triggers:
                if trig.lower() in text_lower:
                    return skill
        return None

    # ── Mutation ─────────────────────────────────────────────

    def enable(self, name: str) -> bool:
        s = self._skills.get(name)
        if s is None:
            return False
        s.enabled = True
        return True

    def disable(self, name: str) -> bool:
        s = self._skills.get(name)
        if s is None:
            return False
        s.enabled = False
        return True

    def stats(self) -> Dict[str, Any]:
        enabled_count = sum(1 for s in self._skills.values() if s.enabled)
        return {
            "total_skills": len(self._skills),
            "enabled": enabled_count,
            "disabled": len(self._skills) - enabled_count,
            "skill_names": [s.name for s in self._skills.values()],
        }


_default: Optional[SkillLoader] = None


def default_loader() -> SkillLoader:
    global _default
    if _default is None:
        _default = SkillLoader()
    return _default
