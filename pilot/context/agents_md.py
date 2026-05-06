"""AGENTS.md cascade 加载（Claude Code / Cursor / OpenAI Agents SDK 通用约定）.

发现顺序:
  1. /etc/claude-code/CLAUDE.md, /etc/agent-pilot/AGENTS.md  (managed)
  2. ~/.claude/CLAUDE.md, ~/.agent-pilot/AGENTS.md           (user)
  3. <repo_root>/AGENTS.md, .agent-pilot/AGENTS.md           (project)
  4. <repo_root>/AGENTS.local.md                              (local, gitignored)

后加载的优先级更高（覆盖前者中冲突部分）。
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("pilot.context.agents_md")


def _candidate_paths(start_dir: Path) -> list[Path]:
    out: list[Path] = []

    # 1. managed
    out += [
        Path("/etc/claude-code/CLAUDE.md"),
        Path("/etc/agent-pilot/AGENTS.md"),
    ]

    # 2. user
    home = Path.home()
    out += [
        home / ".claude" / "CLAUDE.md",
        home / ".agent-pilot" / "AGENTS.md",
    ]

    # 3. project (cascade from filesystem root → start_dir)
    walk = []
    cur = start_dir.resolve()
    while True:
        walk.append(cur)
        if cur.parent == cur:
            break
        cur = cur.parent
    walk.reverse()  # 从根到 start_dir
    for d in walk:
        out += [
            d / "AGENTS.md",
            d / ".agent-pilot" / "AGENTS.md",
            d / "CLAUDE.md",
            d / ".claude" / "CLAUDE.md",
        ]

    # 4. local
    out.append(start_dir / "AGENTS.local.md")
    out.append(start_dir / "CLAUDE.local.md")

    # 去重 + 保留顺序
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        s = str(p)
        if s in seen:
            continue
        seen.add(s)
        uniq.append(p)
    return uniq


def discover_agents_md(start_dir: Path | str | None = None) -> list[Path]:
    """返回所有存在的 AGENTS.md / CLAUDE.md 文件路径."""
    root = Path(start_dir) if start_dir else Path(os.getcwd())
    return [p for p in _candidate_paths(root) if p.exists() and p.is_file()]


_INCLUDE_RE = re.compile(r"^@(\.?/?[\w./\-]+\.md)\s*$", re.MULTILINE)


def _resolve_includes(content: str, base_dir: Path, depth: int = 0) -> str:
    if depth > 5:
        return content
    def _sub(m: re.Match[str]) -> str:
        ref = m.group(1)
        target = (base_dir / ref).resolve()
        if not target.exists():
            return m.group(0)
        try:
            return _resolve_includes(target.read_text(encoding="utf-8"), target.parent, depth + 1)
        except Exception:
            return m.group(0)
    return _INCLUDE_RE.sub(_sub, content)


def load_cascade(start_dir: Path | str | None = None) -> str:
    """加载并合并所有 AGENTS.md，返回单一 markdown 字符串."""
    paths = discover_agents_md(start_dir)
    parts: list[str] = []
    for p in paths:
        try:
            content = p.read_text(encoding="utf-8")
            content = _resolve_includes(content, p.parent)
            # 去 HTML 注释
            content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
            parts.append(f"<!-- source: {p} -->\n{content.strip()}")
        except Exception as e:
            logger.warning("failed to load %s: %s", p, e)
    return "\n\n---\n\n".join(parts)
