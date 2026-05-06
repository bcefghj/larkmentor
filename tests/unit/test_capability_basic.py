"""Capability 层基础测试."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def temp_data_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_DIR", d)
        # 重新导入需要 DATA_DIR 的模块
        import importlib
        from pilot.context import event_log, filesystem_memory
        importlib.reload(event_log)
        importlib.reload(filesystem_memory)
        yield Path(d)


@pytest.fixture(autouse=True)
def no_feishu(monkeypatch):
    """禁用飞书调用，所有工具走本地回退."""
    monkeypatch.setenv("FEISHU_APP_ID", "cli_your_app_id_here")
    monkeypatch.setenv("FEISHU_APP_SECRET", "")


# ── ToolRegistry ─────────────────────────────────────────────────────────────


def test_tool_registry_built_in_loaded():
    from pilot.capability.tools.registry import default_registry

    reg = default_registry()
    names = {s.name for s in reg.list_specs()}
    # 8 个核心工具
    assert "doc.create" in names
    assert "doc.append" in names
    assert "canvas.create" in names
    assert "canvas.add_shape" in names
    assert "slide.generate" in names
    assert "slide.rehearse" in names
    assert "archive.bundle" in names
    assert "voice.transcribe" in names
    assert "im.fetch_thread" in names
    assert "mentor.clarify" in names
    assert "mentor.summarize" in names


def test_tool_registry_read_only_classification():
    from pilot.capability.tools.registry import default_registry

    reg = default_registry()
    # read-only
    assert reg.is_read_only("voice.transcribe")
    assert reg.is_read_only("im.fetch_thread")
    assert reg.is_read_only("mentor.summarize")
    # write
    assert not reg.is_read_only("doc.create")
    assert not reg.is_read_only("doc.append")
    assert not reg.is_read_only("slide.generate")
    assert not reg.is_read_only("canvas.create")


def test_tool_registry_to_llm_schemas():
    from pilot.capability.tools.registry import default_registry

    reg = default_registry()
    schemas = reg.to_llm_schemas(["doc.create", "doc.append"])
    assert len(schemas) == 2
    assert schemas[0]["name"] == "doc.create"
    assert "input_schema" in schemas[0]


# ── 工具执行（mocked LLM, no Feishu）─────────────────────────────────────────


@pytest.mark.asyncio
async def test_doc_create_local_fallback(temp_data_dir):
    from pilot.capability.tools.registry import default_registry

    reg = default_registry()
    out = await reg.execute(
        tool_name="doc.create",
        tool_input={"title": "测试文档"},
        ctx={"step_id": "s1"},
    )
    assert out["title"] == "测试文档"
    assert out["doc_token"]
    assert out["url"]
    assert out["source"] == "local"


@pytest.mark.asyncio
async def test_doc_append_with_intent_fallback(temp_data_dir, monkeypatch):
    """LLM 不可用时也应回退生成 markdown."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("DOUBAO_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from pilot.capability.tools.registry import default_registry

    reg = default_registry()
    out = await reg.execute(
        tool_name="doc.append",
        tool_input={"doc_token": "DOC_X", "intent": "AI Agent 发展报告"},
        ctx={},
    )
    assert out["markdown_chars"] > 200
    assert out["wrote_blocks"] >= 1


@pytest.mark.asyncio
async def test_canvas_create_fallback(temp_data_dir, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("DOUBAO_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from pilot.capability.tools.registry import default_registry

    reg = default_registry()
    out = await reg.execute(
        tool_name="canvas.create",
        tool_input={"title": "产品架构图", "intent": "三件套"},
        ctx={},
    )
    assert out["canvas_id"]
    assert out["mermaid"]
    assert "graph" in out["mermaid"]


@pytest.mark.asyncio
async def test_slide_generate_pptx(temp_data_dir, monkeypatch):
    """slide.generate 应该生成真 .pptx 文件."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("DOUBAO_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from pilot.capability.tools.registry import default_registry

    reg = default_registry()
    out = await reg.execute(
        tool_name="slide.generate",
        tool_input={"title": "测试 PPT", "pages": 6, "intent": "测试"},
        ctx={},
    )
    assert out["slide_id"]
    assert out["pages"] >= 5
    pptx_path = Path(out["pptx_path"])
    # python-pptx 装了就有 .pptx；没装则有 .md
    assert pptx_path.exists() or pptx_path.with_suffix(".md").exists()


@pytest.mark.asyncio
async def test_archive_bundle(temp_data_dir):
    from pilot.capability.tools.registry import default_registry

    reg = default_registry()
    fake_step_results = {
        "s1": {"doc_token": "D1", "url": "https://feishu.cn/docx/D1", "title": "方案"},
        "s2": {"canvas_id": "C1", "mermaid_url": "artifact://x", "title": "架构"},
        "s3": {"slide_id": "S1", "pptx_url": "/artifacts/slides/S1/x.pptx", "title": "PPT"},
    }
    out = await reg.execute(
        tool_name="archive.bundle",
        tool_input={"title": "三件套"},
        ctx={"step_results": fake_step_results},
    )
    assert out["ok"]
    assert out["items_count"] == 3
    assert "summary_md" in out


# ── Workforce ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_planner_heuristic_three_in_one():
    from pilot.capability.workforce import PlannerAgent

    p = PlannerAgent()
    spec = await p.plan(intent="产品方案 + 架构图 + 评审 PPT")
    # 至少三种输出 + 归档 sprint
    assert "doc" in spec.primary_outputs
    assert "canvas" in spec.primary_outputs or "slide" in spec.primary_outputs
    assert len(spec.sprints) >= 2


@pytest.mark.asyncio
async def test_generator_proposes_contract():
    from pilot.capability.workforce import GeneratorAgent

    g = GeneratorAgent()
    contract = await g.propose_contract(
        sprint={"title": "生成 PPT", "goal": "做一份 8 页汇报"},
        spec_title="产品方案",
        sprint_index=2,
    )
    assert contract.sprint_index == 2
    assert contract.deliverables
    assert contract.test_criteria


@pytest.mark.asyncio
async def test_evaluator_review_and_evaluate():
    from pilot.capability.workforce import EvaluatorAgent, GeneratorAgent

    g = GeneratorAgent()
    contract = await g.propose_contract(
        sprint={"title": "生成方案文档", "goal": "1500+ 字"},
        spec_title="X",
        sprint_index=1,
    )
    e = EvaluatorAgent()
    ok = await e.review_contract(contract)
    assert ok
    assert contract.accepted

    score = await e.evaluate(
        contract=contract,
        sprint_result={"markdown_chars": 2000, "wrote_blocks": 80},
    )
    assert score.is_passing()
    assert score.quality >= 80


@pytest.mark.asyncio
async def test_evaluator_fails_short_doc():
    from pilot.capability.workforce import EvaluatorAgent, GeneratorAgent

    g = GeneratorAgent()
    contract = await g.propose_contract(
        sprint={"title": "生成方案文档", "goal": "1500+ 字"},
        spec_title="X",
        sprint_index=1,
    )
    e = EvaluatorAgent()
    score = await e.evaluate(
        contract=contract,
        sprint_result={"markdown_chars": 200, "wrote_blocks": 5},
    )
    assert not score.is_passing()
    assert any("字数不足" in c for c in score.failed_criteria)


def test_clarifier_card_shape():
    from pilot.capability.workforce import Clarifier

    c = Clarifier()
    req = c.build_request(intent="帮我做个汇报")
    card = req.to_card()
    assert card["header"]["title"]["content"].startswith("🤔")
    # 必须有 4 个按钮
    actions_block = next(e for e in card["elements"] if e.get("tag") == "action")
    assert len(actions_block["actions"]) == 4
    # 4 个 action 的 value 都用 pilot.clarify.* 命名空间
    for btn in actions_block["actions"]:
        assert btn["value"]["action"].startswith("pilot.clarify.")


def test_clarifier_choice_expansion():
    from pilot.capability.workforce import Clarifier

    c = Clarifier()
    assert "PPT" in c.expand_choice(intent="给我搞点材料", choice="ppt")
    assert "三件套" in c.expand_choice(intent="给我搞点材料", choice="trio")
    assert c.expand_choice(intent="原意图保留", choice="skip") == "原意图保留"


# ── safe_json ────────────────────────────────────────────────────────────────


def test_safe_json_basic():
    from pilot.llm.safe_json import safe_json_parse

    assert safe_json_parse('{"a": 1}') == {"a": 1}
    assert safe_json_parse('```json\n{"b": 2}\n```') == {"b": 2}
    assert safe_json_parse('前缀文字 { "c": 3 } 后缀') == {"c": 3}
    assert safe_json_parse("不是 JSON") is None
    assert safe_json_parse('{"d": 1,}') == {"d": 1}  # trailing comma 修复
