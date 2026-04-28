"""Memory Tools · FTS5 查询 + Auto Memory 写入。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .registry import tool


@tool(
    name="memory.query",
    description="跨会话 FTS5 全文检索记忆（10ms 级延迟，不用向量 DB）",
    permission="readonly",
    team="any",
)
def query_memory(q: str = "", tenant_id: str = "default", kind: str = "", limit: int = 10) -> Dict[str, Any]:
    from ..memory import default_memory
    mem = default_memory()
    results = mem.query(q, tenant_id=tenant_id, kind=kind or None, limit=limit)
    return {
        "ok": True, "count": len(results),
        "items": [
            {"id": r.id, "kind": r.kind, "content": r.content[:300],
             "ts": r.ts, "user_id": r.user_id, "session_id": r.session_id}
            for r in results
        ],
    }


@tool(
    name="memory.upsert",
    description="写入新记忆（会被 FTS5 索引）",
    permission="write",
    team="any",
)
def upsert_memory(
    content: str = "", kind: str = "fact",
    user_id: str = "", session_id: str = "",
    tenant_id: str = "default",
) -> Dict[str, Any]:
    from ..memory import default_memory
    mem = default_memory()
    mid = mem.upsert(content=content, kind=kind, user_id=user_id, session_id=session_id, tenant_id=tenant_id)
    return {"ok": True, "id": mid}


@tool(
    name="memory.auto_write",
    description="写入 Auto Memory（decisions/patterns/learnings/followups 之一）",
    permission="write",
    team="any",
)
def auto_write(kind: str = "learnings", text: str = "", tenant_id: str = "default") -> Dict[str, Any]:
    if kind not in {"decisions", "patterns", "learnings", "followups"}:
        return {"ok": False, "error": f"invalid kind: {kind}"}
    from ..memory import default_memory
    mem = default_memory()
    mem.append_auto(kind, text, tenant_id=tenant_id)
    return {"ok": True, "kind": kind}


@tool(
    name="memory.auto_read",
    description="读 Auto Memory（最近 N 条 decisions/patterns/learnings/followups）",
    permission="readonly",
    team="any",
)
def auto_read(kind: str = "decisions", tenant_id: str = "default", limit: int = 20) -> Dict[str, Any]:
    from ..memory import default_memory
    mem = default_memory()
    lines = mem.read_auto(kind, tenant_id=tenant_id, limit=limit)
    return {"ok": True, "kind": kind, "lines": lines}
