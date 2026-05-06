"""slide.generate + slide.rehearse tools.

Generates a presentation as a Feishu Docx document. Each slide page is
represented as a H1 heading + bullet points, making it viewable and
shareable directly in Feishu. Also keeps a local Slidev markdown backup.

slide.rehearse generates speaker notes for each page via LLM.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Dict, List

logger = logging.getLogger("pilot.tool.slide")

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "data",
    "pilot_artifacts",
)


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def slide_generate(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}
    title = args.get("title") or "Agent-Pilot 演示"
    if "{{" in str(title):
        title = "Agent-Pilot 演示"
    outline = args.get("outline")
    if not outline or (isinstance(outline, str) and "{{" in outline):
        outline = _default_outline_from_ctx(ctx, title)
    outline = _normalise_outline(outline)

    _ensure_dir()
    slide_id = f"slide_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    md_path = os.path.join(DATA_DIR, f"{slide_id}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_outline_to_slidev_md(title, outline))

    feishu_result = _create_feishu_slide_doc(title, outline)

    result = {
        "slide_id": slide_id,
        "title": title,
        "pages": len(outline),
        "markdown_path": md_path,
        "outline": outline,
    }

    if feishu_result.get("url"):
        result["url"] = feishu_result["url"]
        result["feishu_url"] = feishu_result["url"]
        result["doc_token"] = feishu_result.get("doc_token", "")
        result["source"] = "feishu"
    else:
        result["url"] = f"/artifacts/{slide_id}.md"
        result["source"] = "local"

    return result


def slide_rehearse(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}
    slide_id = args.get("slide_id") or ""
    outline = args.get("outline") or []

    if not outline and slide_id:
        md_path = os.path.join(DATA_DIR, f"{slide_id}.md")
        if os.path.exists(md_path):
            outline = _parse_slidev_md(md_path)

    notes: List[Dict[str, Any]] = []
    for i, page in enumerate(outline or [], start=1):
        notes.append(
            {
                "page": i,
                "title": page.get("title", ""),
                "speaker_note": _speaker_note_for_page(page),
                "duration_sec": 45,
            }
        )

    return {
        "slide_id": slide_id,
        "rehearsal_pages": len(notes),
        "speaker_notes": notes,
    }


def _create_feishu_slide_doc(title: str, outline: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a Feishu Docx document formatted as a presentation."""
    try:
        from config import Config
        if not (Config.FEISHU_APP_ID and Config.FEISHU_APP_SECRET):
            return {}

        import lark_oapi.api.docx.v1 as docx_api
        from bot.feishu_client import get_client

        client = get_client()
        doc_title = f"[演示稿] {title}"
        req = (
            docx_api.CreateDocumentRequest.builder()
            .request_body(docx_api.CreateDocumentRequestBody.builder().title(doc_title).build())
            .build()
        )
        resp = client.docx.v1.document.create(req)
        if not resp.success() or not resp.data or not resp.data.document:
            logger.warning("slide doc create failed: code=%s msg=%s",
                           getattr(resp, "code", "?"), getattr(resp, "msg", "?"))
            return {}

        doc_token = resp.data.document.document_id
        domain = getattr(Config, "FEISHU_TENANT_DOMAIN", "") or "rcnqvnspd31b.feishu.cn"

        blocks = _outline_to_docx_blocks(outline)
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
                logger.info("slide doc: wrote %d blocks to %s", len(blocks), doc_token)
            else:
                logger.warning("slide doc append failed: code=%s msg=%s",
                               getattr(append_resp, "code", "?"), getattr(append_resp, "msg", "?"))

        return {
            "doc_token": doc_token,
            "url": f"https://{domain}/docx/{doc_token}",
        }
    except Exception as e:
        logger.warning("slide feishu doc creation failed: %s", e)
        return {}


def _outline_to_docx_blocks(outline: List[Dict[str, Any]]) -> list:
    """Convert slide outline to Feishu Docx blocks (H1 per page + bullets)."""
    try:
        from lark_oapi.api.docx.v1 import Block, Text, TextElement, TextRun
    except ImportError:
        return []

    blocks = []

    def _make_text_block(text: str, block_type: int):
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

    for i, page in enumerate(outline, 1):
        page_title = page.get("title", f"Slide {i}")
        blocks.append(_make_text_block(f"第{i}页 · {page_title}", 3))

        for bullet in page.get("bullets", []):
            if bullet.strip():
                blocks.append(_make_text_block(bullet, 12))

        blocks.append(_make_text_block("", 2))

    return blocks


# ── LLM outline generation ──


def _generate_outline_via_llm(title: str, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        from llm.llm_client import chat
    except ImportError:
        return []
    if not title:
        return []

    step_results = ctx.get("step_results") or {}
    doc_content = ""
    for r in step_results.values():
        if r.get("doc_token") and r.get("source"):
            doc_content = f"已生成文档 {r.get('doc_token', '')}"
            break

    intent = ctx.get("original_intent", "") or ctx.get("intent", "") or title

    prompt = f"""你是一位专业的演示稿设计专家。请为以下主题设计一份 8-10 页的高质量 PPT 大纲。

主题：{title}
用户原始需求：{intent}
{"关联文档：" + doc_content if doc_content else ""}

请以 JSON 数组格式输出，每个元素包含 title 和 bullets 字段：
[
  {{"title": "封面标题", "bullets": ["副标题信息", "演讲者/团队"]}},
  {{"title": "目录", "bullets": ["章节1", "章节2", "章节3"]}},
  {{"title": "背景与痛点", "bullets": ["痛点1的详细描述（2-3句话）", "痛点2的详细描述", "行业数据支撑"]}},
  ...
]

要求：
1. 8-10 页，结构完整，逻辑清晰
2. 每页 3-5 个要点，每个要点是一句完整的、有信息量的话（不是简单的关键词）
3. 包含：封面、目录/概述、背景分析、核心内容（3-4页深度展开）、案例/数据、总结展望、致谢
4. 内容专业、详实，体现对主题的深入理解
5. 只输出 JSON 数组，不要其他内容"""

    try:
        result = chat(prompt, temperature=0.5)
        if result:
            import json as _json
            import re as _re
            txt = result.strip()
            if txt.startswith("```"):
                m = _re.search(r"```(?:json)?\s*([\s\S]+?)```", txt)
                if m:
                    txt = m.group(1).strip()
            arr = _json.loads(txt)
            if isinstance(arr, list) and len(arr) >= 3:
                return [
                    {"title": str(p.get("title", f"Slide {i}")), "bullets": [str(b) for b in (p.get("bullets") or [])]}
                    for i, p in enumerate(arr, 1)
                ]
    except Exception as e:
        logger.warning("LLM outline generation failed: %s", e)
    return []


def _default_outline_from_ctx(ctx: Dict[str, Any], title: str) -> List[Dict[str, Any]]:
    """Build outline using LLM or fallback to static template."""
    llm_outline = _generate_outline_via_llm(title, ctx)
    if llm_outline:
        return llm_outline

    plan_id = ctx.get("plan_id", "")
    step_results: Dict[str, Dict[str, Any]] = ctx.get("step_results") or {}
    doc_url = ""
    canvas_url = ""
    for r in step_results.values():
        if r.get("doc_token") and r.get("url"):
            doc_url = r["url"]
        if r.get("canvas_id") and r.get("url"):
            canvas_url = r["url"]

    return [
        {"title": title, "bullets": [f"Plan `{plan_id}`", "Agent-Pilot · 一键智能闭环"]},
        {"title": "背景与目标", "bullets": [
            "知识工作者被 IM 打断 → 创意流失",
            "IM → Doc → PPT 全链路需要自动化",
            "本 demo 展示完整闭环",
        ]},
        {"title": "Agent 驱动", "bullets": [
            "Planner 把自然语言拆成 DAG",
            "工具层并行驱动 Doc / Canvas / PPT",
            "所有操作一键可审",
        ]},
        {"title": "多端协同", "bullets": [
            "飞书 App（IM 入口）",
            "Flutter iOS/Android/macOS/Windows",
            "Yjs CRDT 实时同步 + 离线合并",
        ]},
        {"title": "现场 Demo", "bullets": [
            f"文档链接：{doc_url or '（本次运行未生成）'}",
            f"画布链接：{canvas_url or '（本次运行未生成）'}",
            "语音指令实时改 PPT 内容",
        ]},
        {"title": "Thank You", "bullets": [
            "戴尚好 · 中科大",
            "李洁盈 · 港科大",
            "GitHub: bcefghj/Agent-Pilot",
        ]},
    ]


def _normalise_outline(outline) -> List[Dict[str, Any]]:
    if not outline:
        return []
    if isinstance(outline, str):
        outline = [p.strip() for p in outline.split("\n") if p.strip()]
    result: List[Dict[str, Any]] = []
    for i, p in enumerate(outline, start=1):
        if isinstance(p, dict):
            result.append({
                "title": str(p.get("title") or f"Slide {i}"),
                "bullets": [str(b) for b in (p.get("bullets") or [])],
            })
        elif isinstance(p, str):
            result.append({"title": p, "bullets": []})
        else:
            result.append({"title": f"Slide {i}", "bullets": [str(p)]})
    return result


def _outline_to_slidev_md(title: str, outline: List[Dict[str, Any]]) -> str:
    parts = [
        "---",
        "theme: seriph",
        f"title: {title}",
        "class: text-center",
        "---",
        "",
        f"# {title}",
        "",
        "Agent-Pilot · 从 IM 对话到演示稿的一键智能闭环",
        "",
    ]
    for page in outline:
        parts.append("---")
        parts.append("")
        parts.append(f"# {page.get('title', '')}")
        parts.append("")
        for b in page.get("bullets", []):
            parts.append(f"- {b}")
        parts.append("")
    return "\n".join(parts)


def _parse_slidev_md(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        logger.debug("slidev md read failed: %s", e)
        return []
    pages: List[Dict[str, Any]] = []
    for chunk in raw.split("\n---\n"):
        lines = [l for l in chunk.splitlines() if l.strip()]
        if not lines:
            continue
        title = ""
        bullets: List[str] = []
        for l in lines:
            if l.startswith("# "):
                title = l[2:]
            elif l.startswith("- "):
                bullets.append(l[2:])
        if title:
            pages.append({"title": title, "bullets": bullets})
    return pages


def _speaker_note_for_page(page: Dict[str, Any]) -> str:
    title = page.get("title", "")
    bullets = page.get("bullets", [])
    if not title:
        return ""

    note = _generate_speaker_note_via_llm(title, bullets)
    if note:
        return note

    prefix = f"本页主题是「{title}」。"
    if not bullets:
        return prefix
    body = "要点有：" + "；".join(bullets[:3])
    return prefix + body + "。演示时请用自己的语言讲 40-60 秒。"


def _generate_speaker_note_via_llm(title: str, bullets: List[str]) -> str:
    try:
        from llm.llm_client import chat
    except ImportError:
        return ""

    bullets_text = "\n".join(f"- {b}" for b in bullets[:5]) if bullets else "（无要点）"
    prompt = f"""为演示稿的一页生成简短的演讲稿（100-150字），语气自然专业。

页面标题：{title}
页面要点：
{bullets_text}

要求：直接输出演讲稿文本，不要标题或格式标记。"""

    try:
        result = chat(prompt, temperature=0.5)
        if result and len(result.strip()) > 20:
            return result.strip()
    except Exception:
        pass
    return ""
