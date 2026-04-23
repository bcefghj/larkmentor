"""Skills Loader · 三层渐进披露（对齐 Claude Code）

三层：
- L1 metadata（name + description ≤1536 字符）→ 永在 system prompt
- L2 SKILL.md body → 命中时一次性注入
- L3 references/scripts → 按需 Read/Bash

数据源：
- 飞书官方 22 个 Skills: ~/.claude/skills/lark-*
- 自研：.larkmentor/skills/larkmentor-{pilot,mentor,triage,debater,researcher}
- User-Generated（Hermes 启发）：.larkmentor/skills/user-generated/
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("agent.skills")


@dataclass
class Skill:
    name: str
    description: str
    source: str  # "official" / "builtin" / "user_generated"
    body: str = ""  # L2 body
    references: List[str] = field(default_factory=list)  # L3 paths
    path: Path = field(default_factory=Path)

    def metadata_str(self) -> str:
        return f"- **{self.name}** ({self.source}): {self.description[:140]}"


class SkillsLoader:
    def __init__(self) -> None:
        self.skills: Dict[str, Skill] = {}
        self._reload()

    def _reload(self) -> None:
        self.skills.clear()

        # 1. Official lark-cli 22 Skills
        claude_skills_dir = Path.home() / ".claude" / "skills"
        if claude_skills_dir.exists():
            for d in claude_skills_dir.iterdir():
                if d.is_dir() and d.name.startswith("lark-"):
                    skill = self._parse_skill(d, source="official")
                    if skill:
                        self.skills[skill.name] = skill

        # 2. Builtin (self)
        builtin_dir = Path.cwd() / ".larkmentor" / "skills"
        if builtin_dir.exists():
            for d in builtin_dir.iterdir():
                if d.is_dir():
                    source = "user_generated" if d.name == "user-generated" else "builtin"
                    if source == "user_generated":
                        for sub in d.iterdir():
                            if sub.is_dir():
                                s = self._parse_skill(sub, source="user_generated")
                                if s:
                                    self.skills[s.name] = s
                    else:
                        s = self._parse_skill(d, source="builtin")
                        if s:
                            self.skills[s.name] = s

        logger.info("SkillsLoader: %d skills loaded (official=%d builtin=%d user_generated=%d)",
                    len(self.skills),
                    sum(1 for s in self.skills.values() if s.source == "official"),
                    sum(1 for s in self.skills.values() if s.source == "builtin"),
                    sum(1 for s in self.skills.values() if s.source == "user_generated"))

    def _parse_skill(self, d: Path, *, source: str) -> Optional[Skill]:
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            return None
        try:
            content = skill_md.read_text(encoding="utf-8")
        except Exception as e:
            logger.debug("skill read failed %s: %s", skill_md, e)
            return None

        name = d.name
        description = ""
        # YAML frontmatter
        fm_match = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
        body = content
        if fm_match:
            fm_text = fm_match.group(1)
            body = fm_match.group(2)
            for line in fm_text.splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip()

        if not description:
            first_para = body.strip().split("\n\n", 1)[0][:280]
            description = first_para

        # L3 references
        refs: List[str] = []
        for sub in d.iterdir():
            if sub.is_file() and sub.name != "SKILL.md":
                refs.append(str(sub.relative_to(d)))
            elif sub.is_dir():
                for f in sub.rglob("*"):
                    if f.is_file():
                        refs.append(str(f.relative_to(d)))

        return Skill(
            name=name,
            description=description[:1536],
            source=source,
            body=body,
            references=refs[:40],
            path=d,
        )

    # ── Public API ──

    def l1_system_prompt(self) -> str:
        """L1 metadata — goes into every system prompt."""
        if not self.skills:
            return ""
        lines = ["=== AVAILABLE SKILLS (L1 metadata) ==="]
        for s in self.skills.values():
            lines.append(s.metadata_str())
        return "\n".join(lines)

    def l2_body(self, name: str) -> Optional[str]:
        """L2 body — inject when this skill is invoked."""
        skill = self.skills.get(name)
        return skill.body if skill else None

    def l3_read(self, skill_name: str, ref: str) -> Optional[str]:
        """L3 reference read on demand."""
        skill = self.skills.get(skill_name)
        if not skill:
            return None
        p = skill.path / ref
        if not p.exists() or not p.is_file():
            return None
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

    def match_intent(self, intent: str) -> List[str]:
        """Return list of skill names that best match user intent."""
        intent_lower = intent.lower()
        scored = []
        for name, skill in self.skills.items():
            score = 0
            for kw in skill.description.lower().split():
                if len(kw) > 2 and kw in intent_lower:
                    score += 1
            if score > 0:
                scored.append((score, name))
        scored.sort(reverse=True)
        return [n for _, n in scored[:5]]

    def snapshot(self) -> Dict[str, Dict]:
        return {
            name: {
                "source": s.source,
                "description": s.description[:140],
                "refs": len(s.references),
                "body_kb": len(s.body) // 1024,
                "path": str(s.path),
            } for name, s in self.skills.items()
        }


_singleton: Optional[SkillsLoader] = None


def default_skills_loader() -> SkillsLoader:
    global _singleton
    if _singleton is None:
        _singleton = SkillsLoader()
    return _singleton
