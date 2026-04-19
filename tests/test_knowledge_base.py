"""Unit tests for v4 Mentor knowledge base.

Run::

    PYTHONPATH=. pytest -q tests/test_knowledge_base.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def tmp_kb(monkeypatch, tmp_path):
    """Re-route the sqlite db into a tmp dir for each test."""
    from core.mentor import knowledge_base as kb

    db_file = tmp_path / "coach_kb.sqlite"
    monkeypatch.setattr(kb, "_DB_PATH", str(db_file))
    monkeypatch.setattr(kb, "_DATA_DIR", str(tmp_path))
    yield kb


def test_chunk_text_basic(tmp_kb):
    text = "第一段内容。\n\n第二段内容比较长，描述任务背景。\n\n第三段。"
    chunks = tmp_kb.chunk_text(text, chunk_chars=20)
    assert len(chunks) >= 2
    assert all(len(c) <= 30 for c in chunks)


def test_chunk_text_empty(tmp_kb):
    assert tmp_kb.chunk_text("") == []
    assert tmp_kb.chunk_text("   \n  ") == []


def test_import_text_blocks_pii(tmp_kb):
    """PII (phone) in document must be rejected with reason."""
    res = tmp_kb.import_text(
        open_id="ou_test_1",
        source="leak.md",
        text="客户电话 13800138000 需要回访。",
    )
    assert res.ok is False
    assert res.rejected_reason == "pii_detected"
    assert "phone_cn" in res.pii_kinds
    assert tmp_kb.count_chunks("ou_test_1") == 0


def test_import_text_succeeds_without_pii(tmp_kb):
    """With embedding mocked to fail, doc still ingested but no vectors."""
    with mock.patch.object(tmp_kb, "_embed", return_value=[[]]):
        res = tmp_kb.import_text(
            open_id="ou_test_2",
            source="onboarding.md",
            text="入职第一周请阅读《新人手册》并完成 5 个模块的学习。",
        )
    assert res.ok is True
    assert res.chunks_added >= 1
    assert tmp_kb.count_chunks("ou_test_2") >= 1


def test_user_isolation(tmp_kb):
    """User A's docs must not surface in User B's search."""
    with mock.patch.object(tmp_kb, "_embed", return_value=[[]]):
        tmp_kb.import_text("ou_alice", "alice.md", "Alice 喜欢周报使用第一人称。")
        tmp_kb.import_text("ou_bob", "bob.md", "Bob 偏好简洁汇报。")
    hits_alice = tmp_kb.search("ou_alice", "周报")
    hits_bob = tmp_kb.search("ou_bob", "周报")
    assert all(h.chunk.open_id == "ou_alice" for h in hits_alice)
    assert all(h.chunk.open_id == "ou_bob" for h in hits_bob)


def test_search_falls_back_to_bm25_when_embedding_fails(tmp_kb):
    """If embedding API returns empty, BM25 must rank docs."""
    with mock.patch.object(tmp_kb, "_embed", return_value=[[]]):
        tmp_kb.import_text("ou_x", "policy.md", "请假申请需要提前三天提交")
        tmp_kb.import_text("ou_x", "policy.md", "周报每周五下班前提交")
    with mock.patch.object(tmp_kb, "_embed", return_value=[[]]):
        hits = tmp_kb.search("ou_x", "请假")
    assert hits, "BM25 fallback should still return results"
    assert hits[0].method == "bm25"
    assert "请假" in hits[0].chunk.text


def test_delete_user_kb_removes_all(tmp_kb):
    with mock.patch.object(tmp_kb, "_embed", return_value=[[]]):
        tmp_kb.import_text("ou_to_delete", "x.md", "this should be wiped")
    assert tmp_kb.count_chunks("ou_to_delete") >= 1
    n = tmp_kb.delete_user_kb("ou_to_delete")
    assert n >= 1
    assert tmp_kb.count_chunks("ou_to_delete") == 0


def test_search_empty_kb_returns_empty(tmp_kb):
    hits = tmp_kb.search("ou_no_docs", "anything")
    assert hits == []


def test_render_citations_format(tmp_kb):
    chunk = tmp_kb.Chunk(
        id=1, open_id="ou_x", source="rules.md", chunk_idx=2,
        text="规则原文", ts=0,
    )
    hit = tmp_kb.SearchHit(chunk=chunk, score=0.9, method="embedding")
    rendered = tmp_kb.render_citations([hit])
    assert "[来源: rules.md #2]" in rendered
    assert "规则原文" in rendered


def test_to_dict_serialisable(tmp_kb):
    chunk = tmp_kb.Chunk(
        id=1, open_id="ou_x", source="rules.md", chunk_idx=0,
        text="规则", ts=0,
    )
    hit = tmp_kb.SearchHit(chunk=chunk, score=0.812345, method="embedding")
    d = tmp_kb.to_dict(hit)
    assert d["source"] == "rules.md"
    assert d["citation"] == "[来源: rules.md #0]"
    assert d["score"] == 0.8123


def test_import_chunks_concatenates(tmp_kb):
    with mock.patch.object(tmp_kb, "_embed", return_value=[[]]):
        res = tmp_kb.import_chunks(
            "ou_chunks", "wiki.md",
            ["段一", "段二"],
        )
    assert res.ok is True
    assert tmp_kb.count_chunks("ou_chunks") >= 1
