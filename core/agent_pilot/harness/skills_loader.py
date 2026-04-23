"""Claude Code-style 3-layer progressive disclosure Skills loader.

Tier 1 (L1) – Metadata (YAML frontmatter `name` + `description`)
    Always injected into the system prompt. Total budget: 1% of context or
    8000 chars. Enables description-based triggering ("use when ...").

Tier 2 (L2) – SKILL.md body
    Injected as a message when the Skill is "invoked" (description matched
    OR explicitly requested). Persists for the rest of the session.

Tier 3 (L3) – references/ and scripts/
    Loaded on-demand via Read/Bash tools. Zero token cost until needed.

Skill discovery paths (merged, later paths override):
    $LARKMENTOR_SKILLS_HOME (if set)
    ~/.claude/skills/                (where lark-cli installs official Skills)
    ~/.larkmentor/skills/            (user-level custom Skills)
    ./.larkmentor/skills/            (project-level Skills, shared via git)
"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("pilot.harness.skills")


@dataclass
class Skill:
    name: str
    description: str
    when_to_use: str = ""
    body: str = ""                          # SKILL.md minus frontmatter
    path: str = ""                          # directory path
    version: str = "1.0.0"
    allowed_tools: List[str] = field(default_factory=list)
    disable_model_invocation: bool = False
    source: str = "user"                    # user / project / system / official

    def metadata_line(self) -> str:
        """Rendered into system prompt every session."""
        tail = f" (use: {self.when_to_use})" if self.when_to_use else ""
        return f"- **{self.name}** — {self.description}{tail}"


class SkillsLoader:
    def __init__(self, *, search_paths: Optional[List[str]] = None) -> None:
        if search_paths:
            self.search_paths = search_paths
        else:
            self.search_paths = self._default_search_paths()
        self._skills: Dict[str, Skill] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _default_search_paths() -> List[str]:
        out = []
        if os.getenv("LARKMENTOR_SKILLS_HOME"):
            out.append(os.getenv("LARKMENTOR_SKILLS_HOME"))
        out.extend([
            os.path.expanduser("~/.claude/skills"),
            os.path.expanduser("~/.larkmentor/skills"),
            os.path.join(os.getcwd(), ".larkmentor", "skills"),
            os.path.join(os.getcwd(), "skills"),
        ])
        return [p for p in out if p]

    # ── Discovery ──

    def reload(self) -> int:
        with self._lock:
            self._skills.clear()
            count = 0
            for root in self.search_paths:
                if not os.path.isdir(root):
                    continue
                count += self._scan_dir(root)
            logger.info("skills loaded: %d from %d roots", count, len(self.search_paths))
            return count

    def _scan_dir(self, root: str) -> int:
        count = 0
        source = "official" if "claude/skills" in root and "/lark-" in root else "user"
        try:
            for name in os.listdir(root):
                skill_dir = os.path.join(root, name)
                md_path = os.path.join(skill_dir, "SKILL.md")
                if not os.path.isfile(md_path):
                    continue
                try:
                    skill = self._parse(md_path, skill_dir, source=source)
                    with self._lock:
                        self._skills[skill.name] = skill
                    count += 1
                except Exception as exc:
                    logger.warning("skill parse failed: %s (%s)", md_path, exc)
        except Exception as exc:
            logger.warning("skill scan failed %s: %s", root, exc)
        return count

    def _parse(self, md_path: str, skill_dir: str, *, source: str) -> Skill:
        content = open(md_path, "r", encoding="utf-8").read()
        frontmatter: Dict[str, Any] = {}
        body = content
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.S)
        if m:
            raw_fm, body = m.group(1), m.group(2)
            try:
                frontmatter = _parse_simple_yaml(raw_fm)
            except Exception:
                frontmatter = {}
        name = str(frontmatter.get("name") or os.path.basename(skill_dir))
        description = str(frontmatter.get("description") or "").strip()
        when_to_use = str(frontmatter.get("when_to_use") or frontmatter.get("use_when") or "").strip()
        version = str(frontmatter.get("version") or "1.0.0")
        allowed = frontmatter.get("allowed-tools") or frontmatter.get("allowed_tools") or []
        if isinstance(allowed, str):
            allowed = [t.strip() for t in allowed.strip("[]").split(",") if t.strip()]
        elif not isinstance(allowed, list):
            allowed = []
        disable = bool(frontmatter.get("disable-model-invocation") or
                       frontmatter.get("disable_model_invocation") or False)
        return Skill(
            name=name,
            description=description[:400],
            when_to_use=when_to_use[:400],
            body=body.strip()[:16000],
            path=skill_dir,
            version=version,
            allowed_tools=list(allowed),
            disable_model_invocation=disable,
            source=source,
        )

    # ── Public API ──

    def list(self) -> List[Skill]:
        with self._lock:
            return sorted(self._skills.values(), key=lambda s: s.name)

    def get(self, name: str) -> Optional[Skill]:
        with self._lock:
            return self._skills.get(name)

    def metadata_block(self, *, budget_chars: int = 8000) -> str:
        """Render all skill metadata for the system prompt."""
        lines: List[str] = ["## 可用技能（Skills）", ""]
        spent = sum(len(l) + 1 for l in lines)
        for s in self.list():
            if s.disable_model_invocation:
                continue
            line = s.metadata_line()
            if spent + len(line) + 1 > budget_chars:
                lines.append(f"(... 超出预算 {budget_chars} 字符，其余技能需显式调用 ...)")
                break
            lines.append(line)
            spent += len(line) + 1
        return "\n".join(lines)

    def match(self, intent: str, *, top_k: int = 3) -> List[Skill]:
        """Lightweight keyword match: return skills whose description/when_to_use
        most overlaps with intent tokens."""
        intent_lower = intent.lower()
        intent_tokens = set(re.split(r"\s+", intent_lower))
        scored: List[Tuple[int, Skill]] = []
        for s in self.list():
            haystack = f"{s.description}\n{s.when_to_use}".lower()
            if not haystack:
                continue
            score = 0
            for t in intent_tokens:
                if len(t) > 1 and t in haystack:
                    score += 1
            # bonus for substring match of longer phrases
            for phrase in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z]{3,}", intent_lower):
                if phrase in haystack:
                    score += 2
            if score > 0:
                scored.append((score, s))
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:top_k]]

    def invoke_body(self, name: str) -> str:
        s = self.get(name)
        if s is None:
            return ""
        return (
            f"### Skill · {s.name} (v{s.version})\n\n"
            f"{s.description}\n\n"
            f"---\n\n{s.body}\n\n---\n\n"
            f"_Skill directory: `{s.path}`_"
        )


def _parse_simple_yaml(raw: str) -> Dict[str, Any]:
    """Minimal YAML parser for frontmatter (avoid pyyaml dep)."""
    result: Dict[str, Any] = {}
    for line in raw.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1]
            items = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
            result[key] = items
        elif value.lower() in ("true", "false"):
            result[key] = value.lower() == "true"
        else:
            result[key] = value.strip("'\"")
    return result


_default: Optional[SkillsLoader] = None
_default_lock = threading.Lock()


def default_skills() -> SkillsLoader:
    global _default
    with _default_lock:
        if _default is None:
            _default = SkillsLoader()
            try:
                _default.reload()
            except Exception as exc:
                logger.warning("skills default load failed: %s", exc)
        return _default
