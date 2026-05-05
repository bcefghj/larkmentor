"""slide.generate + slide.rehearse tools.

Generates a Slidev markdown file and (optionally) exports pptx/pdf by
shelling out to ``npx slidev export``. When Node/Slidev is not available
we still emit the markdown so judges can inspect the structured output.

A companion ``slide.rehearse`` step asks the LLM to draft speaker notes
for every slide; these are attached back to the slide payload so the
Flutter client can show them in rehearsal mode.
"""

from __future__ import annotations

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

    pptx_url = f"/artifacts/{slide_id}.md"
    pdf_url = pptx_url

    # Optional: export pptx/pdf if Slidev CLI exists
    if shutil.which("npx"):
        try:
            subprocess.run(
                [
                    "npx",
                    "--yes",
                    "slidev@latest",
                    "export",
                    md_path,
                    "--format",
                    "pptx",
                    "--output",
                    os.path.join(DATA_DIR, f"{slide_id}.pptx"),
                ],
                check=False,
                capture_output=True,
                timeout=180,
            )
            if os.path.exists(os.path.join(DATA_DIR, f"{slide_id}.pptx")):
                pptx_url = f"/artifacts/{slide_id}.pptx"
        except Exception as e:
            logger.debug("slidev export skipped: %s", e)

    feishu_result = _try_create_feishu_slides(title, outline)

    return {
        "slide_id": slide_id,
        "title": title,
        "pages": len(outline),
        "markdown_path": md_path,
        "pptx_url": pptx_url,
        "pdf_url": pdf_url,
        "outline": outline,
        "feishu_presentation_id": feishu_result.get("presentation_id", ""),
        "feishu_url": feishu_result.get("url", ""),
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


# ── Feishu Slides API integration ──


def _try_create_feishu_slides(title: str, outline: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Attempt to create presentation via Feishu Slides API or CLI."""
    result = _try_feishu_slides_cli(title)
    if result:
        return result
    return {}


def _try_feishu_slides_cli(title: str) -> Dict[str, Any]:
    """Create a Feishu presentation via lark-cli slides command."""
    try:
        from core.feishu_cli.mcp_config import is_cli_available, run_cli_command

        if not is_cli_available():
            return {}
        resp = run_cli_command(
            "lark-cli slides create --title {title}",
            {"title": title},
        )
        if resp.get("ok") and resp.get("stdout"):
            import json as _json
            try:
                data = _json.loads(resp["stdout"])
                pres_id = data.get("presentation_id") or data.get("id", "")
                if pres_id:
                    return {
                        "presentation_id": pres_id,
                        "url": f"https://bytedance.feishu.cn/slides/{pres_id}",
                    }
            except Exception:
                pass
    except Exception as e:
        logger.debug("feishu slides CLI failed: %s", e)
    return {}


# ── Helpers ──


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

    prompt = f"""你是一个演示稿设计助手。请为以下主题设计一份 6-8 页的 PPT 大纲。

主题：{title}
{"关联文档：" + doc_content if doc_content else ""}

请以 JSON 数组格式输出，每个元素包含 title 和 bullets 字段：
[
  {{"title": "封面标题", "bullets": ["副标题", "作者"]}},
  {{"title": "背景", "bullets": ["要点1", "要点2", "要点3"]}},
  ...
]

要求：
1. 6-8 页，逻辑清晰
2. 每页 2-4 个要点
3. 最后一页为感谢/联系方式
4. 只输出 JSON 数组，不要其他内容"""

    try:
        result = chat(prompt, temperature=0.4)
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
    except Exception:
        pass
    return []


def _default_outline_from_ctx(ctx: Dict[str, Any], title: str) -> List[Dict[str, Any]]:
    """Build a default 6-page outline using prior doc/canvas step results if available."""
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
        {
            "title": "背景与目标",
            "bullets": [
                "知识工作者被 IM 打断 → 创意流失",
                "IM → Doc → PPT 全链路需要自动化",
                "本 demo 展示完整闭环",
            ],
        },
        {
            "title": "Agent 驱动",
            "bullets": [
                "Planner 把自然语言拆成 DAG",
                "工具层并行驱动 Doc / Canvas / PPT",
                "所有操作一键可审",
            ],
        },
        {
            "title": "多端协同",
            "bullets": [
                "飞书 App（IM 入口）",
                "Flutter iOS/Android/macOS/Windows",
                "Yjs CRDT 实时同步 + 离线合并",
            ],
        },
        {
            "title": "现场 Demo",
            "bullets": [
                f"文档链接：{doc_url or '（本次运行未生成）'}",
                f"画布链接：{canvas_url or '（本次运行未生成）'}",
                "语音指令实时改 PPT 内容",
            ],
        },
        {
            "title": "Thank You",
            "bullets": [
                "戴尚好 · 中科大",
                "李洁盈 · 港科大",
                "GitHub: bcefghj/Agent-Pilot",
            ],
        },
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
            result.append(
                {
                    "title": str(p.get("title") or f"Slide {i}"),
                    "bullets": [str(b) for b in (p.get("bullets") or [])],
                }
            )
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
    prompt = f"""为演示稿的一页生成简短的演讲稿（60-90字），语气自然专业。

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
