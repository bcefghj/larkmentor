"""Context 层基础测试."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# 测试前用临时数据目录，避免污染真数据
@pytest.fixture(autouse=True)
def temp_data_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_DIR", d)
        # 重新加载相关模块以应用 env
        import importlib

        from pilot.context import event_log, filesystem_memory
        importlib.reload(event_log)
        importlib.reload(filesystem_memory)
        yield Path(d)


from pilot.context.event_log import EventLog
from pilot.context.filesystem_memory import FilesystemMemory
from pilot.context.context_pack import (
    ContextPackBuilder,
    OutputRequirements,
    SourceMessage,
)
from pilot.context.prompt_assembler import (
    PromptAssembler,
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
)
from pilot.runtime.session import Session, Task


# ── EventLog ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_log_append_and_read():
    log = EventLog("sess_test_1")
    await log.append("user_message", {"text": "hello"})
    await log.append("assistant_text", {"text": "world"})
    all_evts = log.read_all()
    assert len(all_evts) == 2
    assert all_evts[0]["kind"] == "user_message"
    assert all_evts[1]["payload"]["text"] == "world"


@pytest.mark.asyncio
async def test_event_log_read_kind_filter():
    log = EventLog("sess_test_2")
    await log.append("user_message", {"text": "a"})
    await log.append("step_done", {"tool": "doc.create"})
    await log.append("user_message", {"text": "b"})
    msgs = log.read_kind(["user_message"])
    assert len(msgs) == 2
    assert all(m["kind"] == "user_message" for m in msgs)


# ── FilesystemMemory ─────────────────────────────────────────────────────────


def test_filesystem_memory_store_and_resolve():
    mem = FilesystemMemory("sess_test_fs")
    art = mem.store_text("# 长文档\n" + "测试" * 100, kind="report")
    assert art.uri.startswith("artifact://sess_test_fs/")
    assert art.size_bytes > 0
    assert art.sha256

    content = mem.resolve(art.uri)
    assert "测试" in content


def test_filesystem_memory_external():
    mem = FilesystemMemory("sess_test_fs2")
    art = mem.store_external("https://feishu.cn/docx/xxx", summary="飞书文档")
    assert art.uri == "https://feishu.cn/docx/xxx"
    # external resolve 返回空（调用方自行 fetch）
    assert mem.resolve(art.uri) == ""


# ── ContextPack ──────────────────────────────────────────────────────────────


def test_context_pack_builder():
    builder = ContextPackBuilder()
    pack = builder.build(
        task_id="task_xx",
        task_goal="生成产品方案 PPT",
        owner_open_id="ou_xx",
        im_messages=[
            SourceMessage(sender_open_id="u1", text="下周要汇报"),
            SourceMessage(sender_open_id="u2", text="老板很着急"),
        ],
        output_primary="slide",
        output_pages=8,
        output_audience="leader",
    )
    assert pack.task_goal == "生成产品方案 PPT"
    assert len(pack.source_messages) == 2
    assert pack.output_requirements.primary == "slide"
    assert pack.output_requirements.pages == 8

    summary = pack.render_summary()
    assert "IM 对话 · 2 条" in summary["used"]


def test_context_pack_to_dict_round_trip():
    builder = ContextPackBuilder()
    pack = builder.build(
        task_id="t1",
        task_goal="g",
        owner_open_id="ou",
        output_primary="trio",
    )
    d = pack.to_dict()
    assert d["task_goal"] == "g"
    assert d["output_requirements"]["primary"] == "trio"


# ── PromptAssembler ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_assembler_has_boundary():
    pa = PromptAssembler()
    s = Session(user_open_id="ou_test", chat_id="oc_test")
    sys = await pa.assemble_system_prompt(s)
    assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY in sys
    # boundary 之前是静态部分，之后是动态
    static, dynamic = sys.split(SYSTEM_PROMPT_DYNAMIC_BOUNDARY, 1)
    assert "Agent-Pilot V1" in static
    assert "session_id" in dynamic
    assert s.session_id in dynamic


@pytest.mark.asyncio
async def test_prompt_assembler_messages_from_log():
    pa = PromptAssembler(max_history_events=10)
    s = Session(user_open_id="ou", chat_id="oc")

    log = EventLog(s.session_id)
    await log.append("user_message", {"text": "帮我写文档"})
    await log.append("assistant_text", {"text": "好的，正在生成"})
    await log.append("tool_result", {"tool_name": "doc.create", "content": {"doc_token": "X"}})

    t = Task(intent="测试任务", session_id=s.session_id)
    msgs = await pa.assemble_messages(s, t)
    # 至少包含原始意图 + 3 条事件
    assert len(msgs) >= 4
    assert msgs[0]["role"] == "user"
    assert "测试任务" in msgs[0]["content"]
    assert any(m["role"] == "assistant" for m in msgs)
    # tool_result 被压缩
    tool_msgs = [m for m in msgs if "[tool:" in m.get("content", "")]
    assert len(tool_msgs) == 1


def test_estimate_tokens_cjk():
    pa = PromptAssembler()
    msgs = [{"role": "user", "content": "测试中文"}]
    n = pa.estimate_tokens(msgs)
    assert n >= 4  # 4 个汉字 × 1.5 ≈ 6
