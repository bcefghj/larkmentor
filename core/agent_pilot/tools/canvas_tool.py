"""canvas.create + canvas.add_shape tools.

canvas.create creates a Feishu Docx document as a structured canvas,
presenting flowcharts/architectures as text-based diagrams. Also keeps
a local tldraw JSON scene for the Flutter client.

canvas.add_shape adds shapes to the local scene and broadcasts via CRDT.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pilot.tool.canvas")

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "data",
    "pilot_artifacts",
)


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def canvas_create(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}
    title = args.get("title") or f"Canvas {ctx.get('plan_id', '')}"

    _ensure_dir()
    canvas_id = f"canvas_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    path = os.path.join(DATA_DIR, f"{canvas_id}.json")
    scene = {
        "canvas_id": canvas_id,
        "title": title,
        "created_ts": int(time.time()),
        "shapes": [],
        "version": 1,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scene, f, ensure_ascii=False, indent=2)

    feishu_result = _create_feishu_canvas_doc(title, ctx)

    result_url = feishu_result.get("url") or f"/artifacts/{canvas_id}.json"

    _broadcast(ctx, {
        "type": "canvas.created",
        "canvas_id": canvas_id,
        "title": title,
        "url": result_url,
    })

    result = {
        "canvas_id": canvas_id,
        "title": title,
        "local_path": path,
    }

    if feishu_result.get("url"):
        result["url"] = feishu_result["url"]
        result["feishu_url"] = feishu_result["url"]
        result["doc_token"] = feishu_result.get("doc_token", "")
        result["source"] = "feishu"
    else:
        result["url"] = f"/artifacts/{canvas_id}.json"
        result["source"] = "local"

    return result


def canvas_add_shape(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}
    canvas_id = args.get("canvas_id") or ""
    shape_type = args.get("shape_type") or "rect"
    text = args.get("text") or ""

    def _f(v, default):
        if v is None:
            return float(default)
        try:
            return float(v)
        except (TypeError, ValueError):
            return float(default)

    x = _f(args.get("x"), 100)
    y = _f(args.get("y"), 100)
    w = _f(args.get("w"), 200)
    h = _f(args.get("h"), 80)

    path = os.path.join(DATA_DIR, f"{canvas_id}.json")
    if not canvas_id or not os.path.exists(path):
        logger.debug("canvas.add_shape: no canvas %s, seeding demo frame", canvas_id)
        seeded = canvas_create(step, ctx)
        canvas_id = seeded["canvas_id"]
        path = os.path.join(DATA_DIR, f"{canvas_id}.json")

    with open(path, "r", encoding="utf-8") as f:
        scene = json.load(f)

    shape_id = f"s_{uuid.uuid4().hex[:8]}"
    shape = {
        "id": shape_id,
        "type": shape_type,
        "x": x, "y": y, "w": w, "h": h,
        "text": text,
        "ts": int(time.time()),
    }
    if shape_type == "image":
        shape["src"] = args.get("src") or ""
        shape["alt"] = args.get("alt") or text
    elif shape_type == "table":
        rows = args.get("rows") or [[""]]
        shape["rows"] = rows
        shape["cols"] = max(len(r) for r in rows) if rows else 1
    elif shape_type == "sticky":
        shape["color"] = args.get("color") or "#FFD93D"

    scene["shapes"].append(shape)

    if shape_type == "frame" and len(scene["shapes"]) == 1:
        scene["shapes"].extend([
            {"id": f"s_{uuid.uuid4().hex[:8]}", "type": "node", "x": 160, "y": 120, "w": 160, "h": 60, "text": "输入", "ts": int(time.time())},
            {"id": f"s_{uuid.uuid4().hex[:8]}", "type": "node", "x": 400, "y": 120, "w": 160, "h": 60, "text": "Agent Planner", "ts": int(time.time())},
            {"id": f"s_{uuid.uuid4().hex[:8]}", "type": "node", "x": 640, "y": 120, "w": 160, "h": 60, "text": "Doc / Canvas / PPT", "ts": int(time.time())},
            {"id": f"arrow_{uuid.uuid4().hex[:8]}", "type": "arrow", "x": 320, "y": 150, "w": 80, "h": 1, "text": "", "ts": int(time.time())},
            {"id": f"arrow_{uuid.uuid4().hex[:8]}", "type": "arrow", "x": 560, "y": 150, "w": 80, "h": 1, "text": "", "ts": int(time.time())},
        ])
    scene["version"] += 1

    with open(path, "w", encoding="utf-8") as f:
        json.dump(scene, f, ensure_ascii=False, indent=2)

    _broadcast(ctx, {
        "type": "canvas.shape_added",
        "canvas_id": canvas_id,
        "shape": shape,
        "version": scene["version"],
    })

    return {"canvas_id": canvas_id, "shape_id": shape_id, "total_shapes": len(scene["shapes"])}


def _create_feishu_canvas_doc(title: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Create a Feishu Docx document as a structured canvas/whiteboard."""
    try:
        from config import Config
        if not (Config.FEISHU_APP_ID and Config.FEISHU_APP_SECRET):
            return {}

        import lark_oapi.api.docx.v1 as docx_api
        from bot.feishu_client import get_client

        client = get_client()
        doc_title = f"[画布] {title}"
        req = (
            docx_api.CreateDocumentRequest.builder()
            .request_body(docx_api.CreateDocumentRequestBody.builder().title(doc_title).build())
            .build()
        )
        resp = client.docx.v1.document.create(req)
        if not resp.success() or not resp.data or not resp.data.document:
            logger.warning("canvas doc create failed: code=%s msg=%s",
                           getattr(resp, "code", "?"), getattr(resp, "msg", "?"))
            return {}

        doc_token = resp.data.document.document_id
        domain = getattr(Config, "FEISHU_TENANT_DOMAIN", "") or "rcnqvnspd31b.feishu.cn"

        canvas_md = _generate_canvas_content(title, ctx)
        if canvas_md:
            blocks = _canvas_md_to_blocks(canvas_md)
            if blocks:
                from lark_oapi.api.docx.v1 import (
                    CreateDocumentBlockChildrenRequest,
                    CreateDocumentBlockChildrenRequestBody,
                )
                append_req = (
                    CreateDocumentBlockChildrenRequest.builder()
                    .document_id(doc_token)
                    .block_id(doc_token)
                    .request_body(CreateDocumentBlockChildrenRequestBody.builder().children(blocks).build())
                    .build()
                )
                append_resp = client.docx.v1.document_block_children.create(append_req)
                if append_resp.success():
                    logger.info("canvas doc: wrote %d blocks to %s", len(blocks), doc_token)
                else:
                    logger.warning("canvas doc append failed: code=%s msg=%s",
                                   getattr(append_resp, "code", "?"), getattr(append_resp, "msg", "?"))

        return {
            "doc_token": doc_token,
            "url": f"https://{domain}/docx/{doc_token}",
        }
    except Exception as e:
        logger.warning("canvas feishu doc creation failed: %s", e)
        return {}


def _generate_canvas_content(title: str, ctx: Dict[str, Any]) -> str:
    """Use LLM to generate structured canvas content (flowchart/architecture as text)."""
    try:
        from llm.llm_client import chat
    except ImportError:
        return ""

    intent = ctx.get("original_intent", "") or ctx.get("intent", "") or title

    prompt = f"""你是一位专业的架构设计师和流程图专家。请为以下主题生成一份结构化的画布/白板内容。

主题：{title}
用户需求：{intent}

请用 Markdown 格式输出一份可视化架构图/流程图的文字版本，包含：

1. **架构总览** — 用文字描述整体架构或流程
2. **核心模块** — 列出每个模块的名称、职责和关键接口
3. **数据流向** — 用箭头符号(→)描述模块间的数据流转
4. **关键节点说明** — 对重要节点的详细解释
5. **技术选型** — 涉及的技术栈和工具

格式要求：
- 使用 ## 作为大标题，### 作为子标题
- 使用 - 列表描述要点
- 用 → 符号表示流程方向
- 内容详实、专业
- 直接输出 Markdown，不要代码块包裹"""

    try:
        result = chat(prompt, temperature=0.5)
        if result and len(result.strip()) > 100:
            return result.strip()
    except Exception as e:
        logger.warning("canvas LLM generation failed: %s", e)

    return f"""## {title} 架构画布

### 核心架构
- 用户层 → IM 入口（飞书单聊/群聊）
- Agent 层 → Intent Detection → Task Planner → DAG Executor
- 工具层 → Doc Tool / Canvas Tool / Slide Tool
- 存储层 → Feishu Docx API / Local Artifacts

### 数据流
- 用户输入 → IntentDetector → Planner → 并行执行工具
- 工具产出 → CRDT 同步 → 多端展示
- 完成通知 → IM 卡片推送"""


def _canvas_md_to_blocks(md: str) -> list:
    """Convert canvas markdown to Feishu Docx blocks."""
    try:
        from lark_oapi.api.docx.v1 import Block, Text, TextElement, TextRun
    except ImportError:
        return []

    blocks = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line:
            continue

        def _text_block(text: str, block_type: int):
            run = TextRun.builder().content(text).build()
            element = TextElement.builder().text_run(run).build()
            txt = Text.builder().elements([element]).build()
            try:
                bb = Block.builder().block_type(block_type)
                if block_type == 3:
                    return bb.heading1(txt).build()
                elif block_type == 4:
                    return bb.heading2(txt).build()
                elif block_type == 5:
                    return bb.heading3(txt).build()
                elif block_type == 12:
                    return bb.bullet(txt).build()
                else:
                    return bb.text(txt).build()
            except Exception:
                return Block.builder().block_type(2).text(txt).build()

        if line.startswith("# "):
            blocks.append(_text_block(line[2:], 3))
        elif line.startswith("## "):
            blocks.append(_text_block(line[3:], 4))
        elif line.startswith("### "):
            blocks.append(_text_block(line[4:], 5))
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append(_text_block(line[2:], 12))
        else:
            blocks.append(_text_block(line, 2))
    return blocks


def _broadcast(ctx: Dict[str, Any], payload: Dict[str, Any]) -> None:
    try:
        from core.sync.crdt_hub import broadcast_state
        broadcast_state(ctx.get("plan_id", ""), payload)
    except Exception as e:
        logger.debug("canvas broadcast skipped: %s", e)
