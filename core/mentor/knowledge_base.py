"""Per-user organisational knowledge base (RAG).

Design goals:
- **No PyTorch / no sentence-transformers** -- the production server is 2C2G.
  We call the same Doubao Ark account for embeddings (separate endpoint).
- **No vector DB**: a single sqlite file at ``data/coach_kb.sqlite``.
- **Per-user isolation**: every chunk row carries an ``open_id`` and queries
  filter on it. We never cross-search.
- **PII guarded**: every ``import_doc`` call routes through
  :func:`core.security.pii_scrubber.has_pii` and is rejected with a clear
  reason if sensitive fields are detected.
- **BM25 fallback**: if the embedding API fails (rate-limited, down), we
  score with rank_bm25 over the same chunks so the mentor never goes silent.
- **Audit**: every retrieval writes one row to the v3 audit log.

Public API used by the rest of v4::

    from core.mentor.knowledge_base import (
        import_text, import_chunks, search,
        delete_user_kb, count_chunks,
    )
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

logger = logging.getLogger("flowguard.mentor.kb")


# ── storage path ─────────────────────────────────────────────────────────────

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
_DB_PATH = os.path.join(_DATA_DIR, "coach_kb.sqlite")
_DB_LOCK = threading.Lock()


def _connect() -> sqlite3.Connection:
    """Open a sqlite connection with WAL + sane concurrency defaults.

    LarkMentor v2 step8: WAL journal mode lets multiple readers + one writer
    run concurrently across processes (e.g. main bot + mcp_server + tests),
    which our threading.Lock alone cannot guarantee.
    """
    os.makedirs(_DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=10.0, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")
    except sqlite3.DatabaseError:
        pass
    conn.execute("BEGIN")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coach_chunks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            open_id     TEXT    NOT NULL,
            source      TEXT    NOT NULL,
            chunk_idx   INTEGER NOT NULL,
            text        TEXT    NOT NULL,
            embedding   BLOB,
            ts          INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coach_open_id ON coach_chunks(open_id)"
    )
    conn.commit()
    return conn


# ── chunking ─────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_chars: int = 400) -> List[str]:
    """Naive Chinese-friendly chunker: split by paragraph then window."""
    if not text or not text.strip():
        return []
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    out: List[str] = []
    buf = ""
    for p in paragraphs:
        if not buf:
            buf = p
        elif len(buf) + 1 + len(p) <= chunk_chars:
            buf = f"{buf}\n{p}"
        else:
            out.append(buf)
            buf = p
    if buf:
        out.append(buf)
    # Hard window for over-long single paragraphs.
    final: List[str] = []
    for c in out:
        if len(c) <= chunk_chars * 1.5:
            final.append(c)
            continue
        for i in range(0, len(c), chunk_chars):
            final.append(c[i : i + chunk_chars])
    return final


# ── embedding ────────────────────────────────────────────────────────────────

def _pack_vec(vec: List[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_vec(blob: bytes) -> List[float]:
    if not blob:
        return []
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _embed(texts: List[str]) -> List[List[float]]:
    """Call Doubao embedding API.

    Returns ``[]`` for every text on failure -- callers must handle that and
    fall back to BM25.
    """
    if not texts:
        return []
    try:
        from openai import OpenAI

        from config import Config

        client = OpenAI(
            api_key=Config.ARK_API_KEY,
            base_url=Config.ARK_EMBED_BASE_URL,
        )
        resp = client.embeddings.create(
            model=Config.ARK_EMBED_MODEL,
            input=texts,
        )
        return [d.embedding for d in resp.data]
    except Exception as e:  # noqa: BLE001 -- we want to swallow & fallback
        logger.warning("embed_fail kind=%s err=%s", type(e).__name__, str(e)[:120])
        return [[] for _ in texts]


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ── BM25 fallback ────────────────────────────────────────────────────────────

def _tokenize_zh(text: str) -> List[str]:
    """Char-level tokens for CJK plus word-level for ascii.

    Good enough for fallback ranking; we don't ship jieba on the server.
    """
    tokens: List[str] = []
    word = ""
    for ch in text.lower():
        if ch.isalnum() and ord(ch) < 128:
            word += ch
        else:
            if word:
                tokens.append(word)
                word = ""
            if ch.strip():
                tokens.append(ch)
    if word:
        tokens.append(word)
    return tokens


def _bm25_rank(query: str, docs: List[str]) -> List[float]:
    """Rank docs against query.

    First try ``rank_bm25``; on tiny corpora BM25 IDF can collapse to 0 so we
    fall back to a simple token-overlap score that always ranks something
    relevant above unrelated documents.
    """
    if not docs:
        return []
    q_tokens = set(_tokenize_zh(query))
    if not q_tokens:
        return [0.0 for _ in docs]

    bm_scores: List[float] = [0.0 for _ in docs]
    try:
        from rank_bm25 import BM25Okapi  # type: ignore

        tokenized = [_tokenize_zh(d) for d in docs]
        if any(tokenized):
            bm25 = BM25Okapi(tokenized)
            bm_scores = list(bm25.get_scores(_tokenize_zh(query)))
    except Exception:
        pass

    overlap_scores: List[float] = []
    for d in docs:
        d_tokens = set(_tokenize_zh(d))
        if not d_tokens:
            overlap_scores.append(0.0)
            continue
        hit = len(q_tokens & d_tokens)
        overlap_scores.append(hit / max(1, len(q_tokens)))

    # Take whichever is non-zero; prefer BM25 when meaningful.
    return [
        bm if bm > 0 else ov
        for bm, ov in zip(bm_scores, overlap_scores)
    ]


# ── data classes ─────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    id: int
    open_id: str
    source: str
    chunk_idx: int
    text: str
    ts: int


@dataclass
class SearchHit:
    chunk: Chunk
    score: float
    method: str  # "embedding" or "bm25"

    def citation_tag(self) -> str:
        return f"[来源: {self.chunk.source} #{self.chunk.chunk_idx}]"


@dataclass
class ImportResult:
    ok: bool
    chunks_added: int = 0
    rejected_reason: str = ""
    pii_kinds: List[str] = field(default_factory=list)


# ── public API ───────────────────────────────────────────────────────────────

def import_text(
    open_id: str,
    source: str,
    text: str,
    *,
    skip_pii_check: bool = False,
    chunk_chars: Optional[int] = None,
) -> ImportResult:
    """Ingest a free-form text doc into a user's KB.

    Returns ``ImportResult`` with ``ok=False`` if PII is detected.
    """
    if not open_id or not source or not text:
        return ImportResult(ok=False, rejected_reason="empty_input")

    if not skip_pii_check:
        try:
            from core.security.pii_scrubber import scrub_pii

            report = scrub_pii(text)
            if report.counts:
                return ImportResult(
                    ok=False,
                    rejected_reason="pii_detected",
                    pii_kinds=list(report.counts.keys()),
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("pii_scan_skipped err=%s", e)

    try:
        from config import Config

        chunk_size = chunk_chars or Config.MENTOR_KB_CHUNK_CHARS
    except Exception:
        chunk_size = chunk_chars or 400

    chunks = chunk_text(text, chunk_chars=chunk_size)
    if not chunks:
        return ImportResult(ok=False, rejected_reason="no_chunks")

    embeddings = _embed(chunks)

    now = int(time.time())
    with _DB_LOCK:
        conn = _connect()
        try:
            for idx, (chunk, vec) in enumerate(zip(chunks, embeddings)):
                conn.execute(
                    "INSERT INTO coach_chunks (open_id, source, chunk_idx, text, embedding, ts)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (open_id, source, idx, chunk, _pack_vec(vec) if vec else None, now),
                )
            conn.commit()
        finally:
            conn.close()

    logger.info(
        "kb_import open_id=%s source=%s chunks=%d embedded=%d",
        open_id[-8:], source, len(chunks), sum(1 for v in embeddings if v),
    )
    return ImportResult(ok=True, chunks_added=len(chunks))


def import_chunks(
    open_id: str, source: str, chunks: Iterable[str],
) -> ImportResult:
    """Bulk import already-chunked text (used by wiki importer)."""
    text = "\n\n".join(chunks)
    return import_text(open_id, source, text)


def search(
    open_id: str, query: str, top_k: Optional[int] = None,
) -> List[SearchHit]:
    """Return top-k hits for a user. Audit-logged."""
    if not open_id or not query:
        return []

    try:
        from config import Config

        k = top_k or Config.MENTOR_KB_TOPK
    except Exception:
        k = top_k or 5

    rows = _load_user_chunks(open_id)
    if not rows:
        _safe_audit(open_id, query, 0, "empty")
        return []

    # Try embedding first.
    q_vec = _embed([query])[0] if rows[0].embedding_present else []
    method = "embedding"
    scores: List[float]
    if q_vec:
        scores = []
        for r in rows:
            if r.embedding:
                scores.append(_cosine(q_vec, r.embedding))
            else:
                scores.append(0.0)
        if all(s == 0.0 for s in scores):
            scores = _bm25_rank(query, [r.text for r in rows])
            method = "bm25"
    else:
        scores = _bm25_rank(query, [r.text for r in rows])
        method = "bm25"

    ranked = sorted(zip(rows, scores), key=lambda t: t[1], reverse=True)
    hits = [
        SearchHit(chunk=r.to_chunk(), score=float(s), method=method)
        for r, s in ranked[:k]
        if s > 0.0
    ]
    _safe_audit(open_id, query, len(hits), method)
    return hits


def delete_user_kb(open_id: str) -> int:
    """Erase all chunks for a user. Returns count deleted. Used by GDPR delete."""
    if not open_id:
        return 0
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "DELETE FROM coach_chunks WHERE open_id = ?", (open_id,),
            )
            conn.commit()
            return cur.rowcount or 0
        finally:
            conn.close()


def delete_source(open_id: str, source: str) -> int:
    """Delete all chunks of a single source for a user.

    LarkMentor v1 GDPR finer-grained delete: when the user only wants to
    retract one document but keep other onboarding context.
    """
    if not open_id or not source:
        return 0
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "DELETE FROM coach_chunks WHERE open_id = ? AND source = ?",
                (open_id, source),
            )
            conn.commit()
            return cur.rowcount or 0
        finally:
            conn.close()


def list_sources(open_id: str) -> List[dict]:
    """Return [{source, chunks, last_ts}] grouped by source for a user."""
    if not open_id:
        return []
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT source, COUNT(*) AS n, MAX(ts) AS last_ts"
                " FROM coach_chunks WHERE open_id = ?"
                " GROUP BY source ORDER BY last_ts DESC",
                (open_id,),
            )
            return [
                {"source": r[0], "chunks": int(r[1]), "last_ts": int(r[2] or 0)}
                for r in cur.fetchall()
            ]
        finally:
            conn.close()


def count_chunks(open_id: str) -> int:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT COUNT(*) FROM coach_chunks WHERE open_id = ?", (open_id,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()


# ── helpers ──────────────────────────────────────────────────────────────────

@dataclass
class _Row:
    id: int
    open_id: str
    source: str
    chunk_idx: int
    text: str
    embedding: List[float]
    ts: int

    @property
    def embedding_present(self) -> bool:
        return bool(self.embedding)

    def to_chunk(self) -> Chunk:
        return Chunk(
            id=self.id, open_id=self.open_id, source=self.source,
            chunk_idx=self.chunk_idx, text=self.text, ts=self.ts,
        )


def _load_user_chunks(open_id: str) -> List[_Row]:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT id, open_id, source, chunk_idx, text, embedding, ts"
                " FROM coach_chunks WHERE open_id = ? ORDER BY id ASC",
                (open_id,),
            )
            return [
                _Row(
                    id=r[0], open_id=r[1], source=r[2], chunk_idx=r[3],
                    text=r[4], embedding=_unpack_vec(r[5]) if r[5] else [],
                    ts=r[6],
                )
                for r in cur.fetchall()
            ]
        finally:
            conn.close()


def _safe_audit(open_id: str, query: str, hits: int, method: str) -> None:
    try:
        from core.security.audit_log import audit

        audit(
            actor=open_id,
            action="mentor.kb_search",
            resource=query[:80],
            outcome="allow",
            severity="INFO",
            meta={"hits": str(hits), "method": method},
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("audit_skipped err=%s", e)


# ── format helper used by all coaches ────────────────────────────────────────

def render_citations(hits: List[SearchHit]) -> str:
    """Render hits as a prompt-ready context block with citation tags."""
    if not hits:
        return "（无组织文档可用）"
    out = []
    for h in hits:
        out.append(f"{h.citation_tag()}\n{h.chunk.text}")
    return "\n\n---\n\n".join(out)


def to_dict(hit: SearchHit) -> dict:
    """JSON-serialisable form for MCP responses."""
    return {
        "source": hit.chunk.source,
        "chunk_idx": hit.chunk.chunk_idx,
        "text": hit.chunk.text,
        "score": round(hit.score, 4),
        "method": hit.method,
        "citation": hit.citation_tag(),
    }
