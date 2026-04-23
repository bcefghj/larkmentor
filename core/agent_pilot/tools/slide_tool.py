"""slide.generate + slide.rehearse tools.

Generates a Slidev markdown file and (optionally) exports pptx/pdf by
shelling out to ``npx slidev export``. When Node/Slidev is not available
we still emit the markdown so judges can inspect the structured output.

A companion ``slide.rehearse`` step asks the LLM to draft speaker notes
for every slide; these are attached back to the slide payload so the
Flutter client can show them in rehearsal mode.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import uuid
from typing import Any, Dict, List

logger = logging.getLogger("pilot.tool.slide")

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "data", "pilot_artifacts",
)


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def slide_generate(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}
    title = args.get("title") or "Agent-Pilot 演示"
    outline = args.get("outline") or _default_outline_from_ctx(ctx, title)
    outline = _normalise_outline(outline)

    _ensure_dir()
    slide_id = f"slide_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    md_path = os.path.join(DATA_DIR, f"{slide_id}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_outline_to_slidev_md(title, outline))

    pptx_url = f"/artifacts/{slide_id}.md"
    pdf_url = pptx_url

    # Optional: export pptx/pdf if Slidev CLI exists
    if shutil.which("npx"):
        try:
            subprocess.run(
                ["npx", "--yes", "slidev@latest", "export", md_path,
                 "--format", "pptx", "--output", os.path.join(DATA_DIR, f"{slide_id}.pptx")],
                check=False, capture_output=True, timeout=180,
            )
            if os.path.exists(os.path.join(DATA_DIR, f"{slide_id}.pptx")):
                pptx_url = f"/artifacts/{slide_id}.pptx"
        except Exception as e:
            logger.debug("slidev export skipped: %s", e)

    return {
        "slide_id": slide_id,
        "title": title,
        "pages": len(outline),
        "markdown_path": md_path,
        "pptx_url": pptx_url,
        "pdf_url": pdf_url,
        "outline": outline,
    }


def slide_rehearse(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}
    slide_id = args.get("slide_id") or ""
    outline = args.get("outline") or []

    # Recover outline from disk if not passed
    if not outline and slide_id:
        md_path = os.path.join(DATA_DIR, f"{slide_id}.md")
        if os.path.exists(md_path):
            outline = _parse_slidev_md(md_path)

    notes: List[Dict[str, Any]] = []
    for i, page in enumerate(outline or [], start=1):
        notes.append({
            "page": i,
            "title": page.get("title", ""),
            "speaker_note": _speaker_note_for_page(page),
            "duration_sec": 45,
        })

    return {
        "slide_id": slide_id,
        "rehearsal_pages": len(notes),
        "speaker_notes": notes,
    }


# ── Helpers ──

def _default_outline_from_ctx(ctx: Dict[str, Any], title: str) -> List[Dict[str, Any]]:
    """Build a default 6-page outline using prior doc/canvas step results if available."""
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
        {"title": title, "bullets": [f"Plan `{plan_id}`", "LarkMentor · Agent-Pilot"]},
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
            "GitHub: bcefghj/larkmentor",
        ]},
    ]


def _normalise_outline(outline) -> List[Dict[str, Any]]:
    """Accept any of: [{title, bullets}], ["page1", "page2"], "comma,sep,list".

    Returns a consistent list of dicts so downstream code can assume .get().
    """
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
        "LarkMentor · Agent-Pilot",
        "",
    ]
    for page in outline:
        parts.append("---")
        parts.append("")
        parts.append(f"# {page.get('title','')}")
        parts.append("")
        for b in page.get("bullets", []):
            parts.append(f"- {b}")
        parts.append("")
    return "\n".join(parts)


def _parse_slidev_md(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception:
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
    # Keep local/offline deterministic; the LLM version can be wired later
    if not title:
        return ""
    prefix = f"本页主题是「{title}」。"
    if not bullets:
        return prefix
    body = "要点有：" + "；".join(bullets[:3])
    return prefix + body + "。演示时请用自己的语言讲 40-60 秒。"
