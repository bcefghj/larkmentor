"""P4 · ContextService 上下文构建测试 (PRD §7 + Q4)."""
from __future__ import annotations

import os
import tempfile

import pytest

from core.agent_pilot.application import (
    ContextBuildOptions,
    ContextService,
    parse_feishu_doc_token,
)
from core.agent_pilot.domain import (
    ContextPack,
    MaterialKind,
    SourceDoc,
    SourceMessage,
    UserMaterial,
)


# ── 飞书 doc_token 解析 ────────────────────────────────────────────────────


def test_parse_feishu_doc_token_from_docx_url():
    url = "https://example.feishu.cn/docx/ABCdef123456"
    assert parse_feishu_doc_token(url) == "ABCdef123456"


def test_parse_feishu_doc_token_from_wiki_url():
    url = "https://example.feishu.cn/wiki/XYZqrst99887"
    assert parse_feishu_doc_token(url) == "XYZqrst99887"


def test_parse_feishu_doc_token_bare_token():
    assert parse_feishu_doc_token("ABCdef123456") == "ABCdef123456"


def test_parse_feishu_doc_token_unrelated_url():
    assert parse_feishu_doc_token("https://google.com") is None


def test_parse_feishu_doc_token_empty():
    assert parse_feishu_doc_token("") is None


# ── ContextService.build 主流程 ───────────────────────────────────────────


@pytest.fixture
def svc(tmp_path):
    return ContextService(upload_root=str(tmp_path))


def test_build_minimum_pack(svc):
    opts = ContextBuildOptions(
        task_id="t1", task_goal="活动复盘", owner_open_id="u1",
        output_primary="ppt", output_audience="leader",
    )
    cp = svc.build(opts)
    assert cp.task_id == "t1"
    assert cp.task_goal == "活动复盘"
    assert cp.output_requirements.primary == "ppt"
    assert cp.output_requirements.audience == "leader"
    assert cp.constraints.must_cite is True
    assert cp.pack_id.startswith("ctx-")


def test_build_with_im_messages(svc):
    msgs = [
        SourceMessage(sender_open_id="u1", text="下周做汇报"),
        SourceMessage(sender_open_id="u2", text="我有数据"),
    ]
    cp = svc.build(
        ContextBuildOptions(task_id="t1", task_goal="x", owner_open_id="u1"),
        im_messages=msgs,
    )
    assert len(cp.source_messages) == 2
    assert cp.total_chars() == 9  # 4 + 5 chars


def test_build_with_user_uploads_and_links(svc, tmp_path):
    f = tmp_path / "demo.docx"
    f.write_text("hello world", encoding="utf-8")
    materials = [
        UserMaterial(kind=MaterialKind.LINK, url="https://example.com/x", title="参考链接"),
        UserMaterial(kind=MaterialKind.UPLOAD, file_path=str(f), title="资料"),
    ]
    cp = svc.build(
        ContextBuildOptions(task_id="t2", task_goal="x", owner_open_id="u1"),
        user_materials=materials,
    )
    assert len(cp.user_added_materials) == 2
    # source_docs 同步
    assert len(cp.source_docs) == 2
    assert any(d.kind == MaterialKind.LINK for d in cp.source_docs)
    assert any(d.kind == MaterialKind.UPLOAD for d in cp.source_docs)


def test_build_extra_doc_refs_with_external_link(svc):
    cp = svc.build(
        ContextBuildOptions(task_id="t1", task_goal="x", owner_open_id="u1"),
        extra_doc_refs=["https://example.com/some.html"],
    )
    assert any(d.kind == MaterialKind.LINK for d in cp.source_docs)


def test_build_extra_doc_refs_with_feishu_no_fetcher(svc):
    """有 token 但没注入 fetcher → 占位 source_doc，permission_ok=False."""
    url = "https://example.feishu.cn/docx/AAA111222333"
    cp = svc.build(
        ContextBuildOptions(task_id="t1", task_goal="x", owner_open_id="u1"),
        extra_doc_refs=[url],
    )
    assert len(cp.source_docs) == 1
    d = cp.source_docs[0]
    assert d.kind == MaterialKind.FEISHU_DOC
    assert d.doc_token == "AAA111222333"
    assert not d.permission_ok


def test_build_extra_doc_refs_with_feishu_fetcher_injected(tmp_path):
    """注入飞书 fetcher → 真实抓取 + summary 填充."""
    captured = {}

    def fetcher(token: str):
        captured["token"] = token
        return SourceDoc(
            kind=MaterialKind.FEISHU_DOC,
            title="复盘文档",
            doc_token=token,
            url=f"https://x.feishu.cn/docx/{token}",
            summary="季度活动复盘要点",
            excerpt="本次校园活动 ...",
            permission_ok=True,
        )

    svc = ContextService(feishu_doc_fetcher=fetcher, upload_root=str(tmp_path))
    cp = svc.build(
        ContextBuildOptions(task_id="t1", task_goal="x", owner_open_id="u1"),
        extra_doc_refs=["https://x.feishu.cn/docx/XYZ987"],
    )
    assert captured["token"] == "XYZ987"
    assert cp.source_docs[0].permission_ok
    assert cp.source_docs[0].summary == "季度活动复盘要点"


def test_history_recaller_injected(tmp_path):
    captured = {"called_with": None}

    def recaller(query: str, top_k: int):
        captured["called_with"] = (query, top_k)
        return [SourceDoc(kind=MaterialKind.FEISHU_DOC, title="历史方案", summary="去年的方案")]

    svc = ContextService(history_recaller=recaller, upload_root=str(tmp_path))
    cp = svc.build(ContextBuildOptions(task_id="t1", task_goal="复盘", owner_open_id="u1"))
    assert captured["called_with"] == ("复盘", 3)
    assert any(d.kind == MaterialKind.HISTORY_TASK for d in cp.source_docs)


def test_history_recaller_failure_does_not_break_build(tmp_path):
    def recaller(query: str, top_k: int):
        raise RuntimeError("recall service down")
    svc = ContextService(history_recaller=recaller, upload_root=str(tmp_path))
    cp = svc.build(ContextBuildOptions(task_id="t1", task_goal="x", owner_open_id="u1"))
    assert cp is not None  # 没有抛异常


def test_add_link_material(svc):
    cp = svc.build(ContextBuildOptions(task_id="t1", task_goal="x", owner_open_id="u1"))
    m = svc.add_link_material(cp, url="https://x.com/y", note="参考")
    assert m.kind == MaterialKind.LINK
    assert any(d.url == "https://x.com/y" for d in cp.source_docs)


def test_add_user_upload(svc, tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("hi")
    cp = svc.build(ContextBuildOptions(task_id="t1", task_goal="x", owner_open_id="u1"))
    m = svc.add_user_upload(cp, file_path=str(f), title="my", body_excerpt="body")
    assert m.kind == MaterialKind.UPLOAD
    assert any(d.kind == MaterialKind.UPLOAD for d in cp.source_docs)


def test_render_confirm_summary(svc):
    cp = svc.build(
        ContextBuildOptions(
            task_id="t1", task_goal="活动复盘", owner_open_id="u1",
            output_primary="ppt", output_audience="leader",
        ),
        im_messages=[SourceMessage(sender_open_id="u1", text="msg")],
    )
    summary = svc.render_confirm_summary(cp)
    assert summary["task_goal"] == "活动复盘"
    assert summary["msg_count"] == 1
    assert summary["output_primary"] == "ppt"
    assert summary["has_min_info"] is True


def test_memory_resolver_injected(tmp_path):
    captured = {"called": False}

    def resolver(**kwargs):
        captured["called"] = True
        captured["kwargs"] = kwargs
        return "## Enterprise\n我司财年 4-3 月"

    svc = ContextService(memory_resolver=resolver, upload_root=str(tmp_path))
    opts = ContextBuildOptions(
        task_id="t1", task_goal="x", owner_open_id="u1",
        tenant_id="T1", workspace_id="W1", department_id="D1",
        chat_id="g1", user_id="u1", session_id="s1",
    )
    md = svc.resolve_memory_md(opts)
    assert "财年" in md
    assert captured["called"]
    assert captured["kwargs"]["tenant"] == "T1"
    assert captured["kwargs"]["workspace"] == "W1"


def test_memory_resolver_missing_returns_empty(svc):
    opts = ContextBuildOptions(task_id="t1", task_goal="x", owner_open_id="u1")
    assert svc.resolve_memory_md(opts) == ""


def test_memory_resolver_failure_returns_empty(tmp_path):
    def resolver(**kwargs):
        raise RuntimeError("oops")
    svc = ContextService(memory_resolver=resolver, upload_root=str(tmp_path))
    opts = ContextBuildOptions(task_id="t1", task_goal="x", owner_open_id="u1")
    assert svc.resolve_memory_md(opts) == ""
