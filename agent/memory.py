"""Memory Layer · 4 层 CLAUDE.md 继承 + Auto Memory + SQLite FTS5 召回

对齐 Claude Code 4 层 hierarchy（code.claude.com/docs/en/memory）：
- Layer 1 Enterprise：/etc/larkmentor/LARKMENTOR.md
- Layer 2 Project：./LARKMENTOR.md
- Layer 3 User：~/.larkmentor/LARKMENTOR.md
- Layer 4 Local：./LARKMENTOR.local.md（gitignored）

Auto Memory（Agent 自写，Claude Code 独家 + Hermes 启发）：
- ~/.larkmentor/auto_memory/{tenant_id}/decisions.md
- ~/.larkmentor/auto_memory/{tenant_id}/patterns.md
- ~/.larkmentor/auto_memory/{tenant_id}/learnings.md
- ~/.larkmentor/auto_memory/{tenant_id}/followups.md

跨会话召回：SQLite + FTS5 全文索引（借鉴 Hermes，10ms 级延迟，不用向量 DB）。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent.memory")


# ── File locations ──

def _enterprise_paths() -> List[Path]:
    return [
        Path("/etc/larkmentor/LARKMENTOR.md"),
        Path("/Library/Application Support/LarkMentor/LARKMENTOR.md"),
        Path("C:/ProgramData/LarkMentor/LARKMENTOR.md"),
    ]


def _project_paths() -> List[Path]:
    cwd = Path.cwd()
    return [cwd / "LARKMENTOR.md", cwd / ".larkmentor" / "LARKMENTOR.md"]


def _user_paths() -> List[Path]:
    home = Path(os.getenv("LARKMENTOR_HOME", str(Path.home() / ".larkmentor")))
    return [home / "LARKMENTOR.md", Path.home() / ".larkmentor" / "LARKMENTOR.md"]


def _local_paths() -> List[Path]:
    return [Path.cwd() / "LARKMENTOR.local.md"]


@dataclass
class MemoryEntry:
    id: int
    tenant_id: str
    user_id: str
    session_id: str
    kind: str  # decision / pattern / learning / followup / fact / summary
    content: str
    ts: int


class MemoryLayer:
    """4 层 CLAUDE.md 继承 + Auto Memory + SQLite FTS5."""

    def __init__(self, *, db_path: Optional[Path] = None) -> None:
        home = Path(os.getenv("LARKMENTOR_HOME", str(Path.home() / ".larkmentor")))
        home.mkdir(parents=True, exist_ok=True)
        self.home = home
        self.db_path = db_path or home / "memory.sqlite"
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    user_id TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts INTEGER NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(content, content='memories', content_rowid='id');
                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories
                    BEGIN
                        INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
                    END;
                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories
                    BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, content)
                        VALUES ('delete', old.id, old.content);
                    END;
                CREATE INDEX IF NOT EXISTS idx_mem_tenant_ts ON memories(tenant_id, ts DESC);
                CREATE INDEX IF NOT EXISTS idx_mem_kind ON memories(kind);
            """)
            conn.commit()
            conn.close()

    # ── System prompt composition (4-layer cascade) ──

    def build_system_prompt(self) -> str:
        """Cascade 4 layers; later layer wins (append) to preserve all guidance."""
        pieces: List[str] = []

        def _read_first(paths: List[Path], label: str) -> None:
            for p in paths:
                try:
                    if p.exists():
                        body = p.read_text(encoding="utf-8", errors="replace").strip()
                        if body:
                            pieces.append(f"=== {label} ({p}) ===\n{body}")
                            return
                except Exception as e:
                    logger.debug("memory read %s failed: %s", p, e)

        _read_first(_enterprise_paths(), "ENTERPRISE POLICY")
        _read_first(_project_paths(), "PROJECT MEMORY")
        _read_first(_user_paths(), "USER MEMORY")
        _read_first(_local_paths(), "LOCAL OVERRIDE")
        return "\n\n".join(pieces)

    # ── Auto Memory (4 files) ──

    def _auto_memory_dir(self, tenant_id: str = "default") -> Path:
        d = self.home / "auto_memory" / tenant_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def append_auto(self, kind: str, text: str, *, tenant_id: str = "default") -> None:
        """Append to one of decisions / patterns / learnings / followups."""
        assert kind in {"decisions", "patterns", "learnings", "followups"}
        f = self._auto_memory_dir(tenant_id) / f"{kind}.md"
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"\n- [{ts}] {text.strip()}"
        try:
            with open(f, "a", encoding="utf-8") as fp:
                fp.write(line)
        except Exception as e:
            logger.warning("append_auto %s failed: %s", kind, e)

    def read_auto(self, kind: str, *, tenant_id: str = "default", limit: int = 20) -> List[str]:
        f = self._auto_memory_dir(tenant_id) / f"{kind}.md"
        if not f.exists():
            return []
        try:
            lines = [l for l in f.read_text(encoding="utf-8").splitlines() if l.strip().startswith("-")]
            return lines[-limit:]
        except Exception:
            return []

    # ── SQLite FTS5 ──

    def upsert(
        self, content: str, *, kind: str = "fact",
        user_id: str = "", session_id: str = "",
        tenant_id: str = "default",
    ) -> int:
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            cur = conn.execute(
                "INSERT INTO memories (tenant_id, user_id, session_id, kind, content, ts) VALUES (?, ?, ?, ?, ?, ?)",
                (tenant_id, user_id, session_id, kind, content[:20_000], int(time.time()))
            )
            conn.commit()
            mid = cur.lastrowid
            conn.close()
            return mid

    def query(
        self, q: str, *, tenant_id: str = "default",
        kind: Optional[str] = None, limit: int = 10,
    ) -> List[MemoryEntry]:
        """FTS5 full-text search."""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                safe_q = q.replace('"', '').strip()
                if not safe_q:
                    rows = conn.execute(
                        "SELECT * FROM memories WHERE tenant_id=? ORDER BY ts DESC LIMIT ?",
                        (tenant_id, limit),
                    ).fetchall()
                elif kind:
                    rows = conn.execute(
                        """
                        SELECT m.* FROM memories_fts f JOIN memories m ON f.rowid = m.id
                        WHERE f.content MATCH ? AND m.tenant_id = ? AND m.kind = ?
                        ORDER BY m.ts DESC LIMIT ?
                        """, (safe_q, tenant_id, kind, limit)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT m.* FROM memories_fts f JOIN memories m ON f.rowid = m.id
                        WHERE f.content MATCH ? AND m.tenant_id = ?
                        ORDER BY m.ts DESC LIMIT ?
                        """, (safe_q, tenant_id, limit)
                    ).fetchall()
            except sqlite3.OperationalError as e:
                logger.warning("FTS5 query fallback (%s)", e)
                rows = conn.execute(
                    "SELECT * FROM memories WHERE tenant_id=? AND content LIKE ? ORDER BY ts DESC LIMIT ?",
                    (tenant_id, f"%{q}%", limit),
                ).fetchall()
            conn.close()
        out: List[MemoryEntry] = []
        for row in rows:
            out.append(MemoryEntry(
                id=row["id"], tenant_id=row["tenant_id"], user_id=row["user_id"],
                session_id=row["session_id"], kind=row["kind"],
                content=row["content"], ts=row["ts"],
            ))
        return out

    def recent(self, *, tenant_id: str = "default", limit: int = 10) -> List[MemoryEntry]:
        return self.query("", tenant_id=tenant_id, limit=limit)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            by_kind = dict(conn.execute("SELECT kind, COUNT(*) FROM memories GROUP BY kind").fetchall())
            conn.close()
        return {
            "db_path": str(self.db_path),
            "home": str(self.home),
            "total_memories": total,
            "by_kind": by_kind,
            "auto_memory_dirs": [str(d) for d in (self.home / "auto_memory").glob("*") if d.is_dir()],
            "system_prompt_layers": {
                "enterprise": any(p.exists() for p in _enterprise_paths()),
                "project": any(p.exists() for p in _project_paths()),
                "user": any(p.exists() for p in _user_paths()),
                "local": any(p.exists() for p in _local_paths()),
            },
        }


_singleton: Optional[MemoryLayer] = None


def default_memory() -> MemoryLayer:
    global _singleton
    if _singleton is None:
        _singleton = MemoryLayer()
    return _singleton
