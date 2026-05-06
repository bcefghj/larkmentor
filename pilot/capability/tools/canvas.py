"""canvas.create / canvas.add_shape — 画布工具.

输出形态:
  - tldraw JSON（前端可加载）
  - Mermaid 代码（飞书 Docx 自动渲染流程图）
  - 飞书白板（可选；当 FEISHU_APP_ID 配置时尝试创建）
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any

from pilot.context.filesystem_memory import FilesystemMemory

logger = logging.getLogger("pilot.tool.canvas")


def register_to(reg) -> None:
    reg.register(
        "canvas.create",
        description="基于上游 doc.append 的 markdown 生成架构图/画布（tldraw JSON + Mermaid）",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "intent": {"type": "string", "description": "用户原始意图"},
            },
            "required": ["title"],
        },
        read_only=False,
        namespace="pilot",
    )(canvas_create)

    reg.register(
        "canvas.add_shape",
        description="在画布上添加节点/箭头/分组",
        input_schema={
            "type": "object",
            "properties": {
                "canvas_id": {"type": "string"},
                "shape_type": {"type": "string", "enum": ["frame", "rect", "ellipse", "arrow"]},
                "text": {"type": "string"},
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
            "required": ["canvas_id", "shape_type"],
        },
        read_only=False,
        namespace="pilot",
    )(canvas_add_shape)


# ── 实现 ──


async def canvas_create(
    *,
    title: str,
    intent: str = "",
    _ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    upstream_md = _extract_upstream_doc(_ctx)
    spec = await _llm_design_canvas(title=title, intent=intent, upstream_md=upstream_md)

    cid = f"canvas_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    session_id = _safe_session_id(_ctx)
    mem = FilesystemMemory(session_id=session_id)

    tldraw_art = mem.store_json(spec.get("tldraw") or {}, kind="canvas",
                                summary=f"tldraw spec for {title}",
                                tool="canvas.create",
                                step_id=(_ctx or {}).get("step_id", ""))
    mermaid_art = mem.store_text(spec.get("mermaid") or _fallback_mermaid(title),
                                 kind="canvas",
                                 mime_type="text/markdown",
                                 summary=f"mermaid for {title}",
                                 tool="canvas.create",
                                 step_id=(_ctx or {}).get("step_id", ""))

    return {
        "canvas_id": cid,
        "title": title,
        "tldraw_url": tldraw_art.uri,
        "mermaid_url": mermaid_art.uri,
        "mermaid": spec.get("mermaid", ""),
        "node_count": len(spec.get("tldraw", {}).get("shapes", [])),
        "source": "local",
    }


async def canvas_add_shape(
    *,
    canvas_id: str,
    shape_type: str,
    text: str = "",
    x: float = 0,
    y: float = 0,
    _ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "canvas_id": canvas_id,
        "shape": {
            "id": f"shape_{uuid.uuid4().hex[:6]}",
            "type": shape_type,
            "text": text,
            "x": x,
            "y": y,
        },
    }


# ── 辅助 ──


def _safe_session_id(ctx: dict[str, Any] | None) -> str:
    if ctx and ctx.get("session"):
        try:
            return ctx["session"].session_id
        except Exception:
            return ""
    return ""


def _extract_upstream_doc(ctx: dict[str, Any] | None) -> str:
    """从 step_results 中找最近一个 doc.append 的 markdown."""
    if not ctx:
        return ""
    results = ctx.get("step_results") or {}
    for r in reversed(list(results.values())):
        if isinstance(r, dict):
            if "markdown_chars" in r and "markdown_artifact" in r:
                # 本地落盘的 markdown，可恢复
                art = r.get("markdown_artifact", {})
                if isinstance(art, dict) and art.get("uri"):
                    mem = FilesystemMemory()
                    return mem.resolve(art["uri"])
            if "markdown" in r and isinstance(r["markdown"], str):
                return r["markdown"]
    return ""


async def _llm_design_canvas(*, title: str, intent: str, upstream_md: str) -> dict[str, Any]:
    """让 LLM 输出 tldraw JSON + mermaid 字符串."""
    try:
        from pilot.llm.client import default_client
        from pilot.llm.safe_json import safe_json_parse

        prompt = f"""请基于以下信息设计一份架构图/流程图。

标题：{title}
用户意图：{intent or '（无）'}
上游文档摘要：
{upstream_md[:1500] or '（无上游文档）'}

输出严格 JSON：
{{
  "mermaid": "graph LR\\n  A[模块A] --> B[模块B]\\n  ...",
  "tldraw": {{
    "shapes": [
      {{"id": "s1", "type": "rect", "text": "模块A", "x": 0, "y": 0}},
      {{"id": "s2", "type": "rect", "text": "模块B", "x": 200, "y": 0}}
    ],
    "arrows": [
      {{"from": "s1", "to": "s2", "label": ""}}
    ]
  }}
}}

要求：
- mermaid 用 graph LR/TB；不要 quote escape
- tldraw 至少 4 个节点 + 3 条箭头
- 中文标签
- 不要 markdown 代码块、不要解释、直接输出 JSON
"""
        client = default_client()
        result = await client.chat(
            system="你是 Agent-Pilot 的架构师，擅长把方案转成结构图。",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2048,
        )
        for block in result.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                obj = safe_json_parse(block.get("text", ""), expected_type=dict, debug_label="canvas")
                if obj:
                    return obj
    except Exception as e:
        logger.warning("canvas LLM failed: %s", e)

    return _fallback_spec(title)


def _fallback_spec(title: str) -> dict[str, Any]:
    return {
        "mermaid": _fallback_mermaid(title),
        "tldraw": {
            "shapes": [
                {"id": "s1", "type": "rect", "text": "用户", "x": 0, "y": 0},
                {"id": "s2", "type": "rect", "text": title[:8] or "核心系统", "x": 200, "y": 0},
                {"id": "s3", "type": "rect", "text": "外部服务", "x": 400, "y": 0},
                {"id": "s4", "type": "rect", "text": "存储", "x": 200, "y": 150},
            ],
            "arrows": [
                {"from": "s1", "to": "s2", "label": "请求"},
                {"from": "s2", "to": "s3", "label": "调用"},
                {"from": "s2", "to": "s4", "label": "持久化"},
            ],
        },
    }


def _fallback_mermaid(title: str) -> str:
    return (
        "graph LR\n"
        "    U[用户] --> S[" + (title[:8] or "核心系统") + "]\n"
        "    S --> E[外部服务]\n"
        "    S --> D[存储]\n"
    )
