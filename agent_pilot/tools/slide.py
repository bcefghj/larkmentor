"""slide.generate + slide.rehearse – v13 真 PPTX 三件套.

This is the single source of truth for "演示稿/PPT" generation. It produces:

1. **`.pptx`** via ``python-pptx`` – a real PowerPoint file with cover, TOC,
   content slides (title + bullets + speaker notes), and a Thank-You page.
2. **Slidev HTML** – a Slidev-formatted markdown that can be built into a
   static slideshow with ``npx @slidev/cli build``. Falls back to a
   Markdown-only artifact when ``npx`` isn't available.
3. **Speaker-notes Markdown** – a per-page narration script. (The Markdown is
   always produced; TTS mp3 is best-effort.)

Optional: TTS mp3 (gTTS) when ``AGENT_PILOT_ENABLE_TTS=1`` is set and the
network can reach Google.

The tool also creates a **preview Feishu Docx** (one heading + bullets per
slide) so users on iOS/Android can flip through it natively. The .pptx file
itself is uploaded to Feishu cloud Drive when an ``FEISHU_FOLDER_TOKEN`` is
configured; otherwise it's served via the Dashboard ``/artifacts/slides/...``
static route.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent_pilot.llm.safe_json import safe_json_parse

logger = logging.getLogger("agent_pilot.tool.slide")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ARTIFACTS_DIR = PROJECT_ROOT / "data" / "artifacts" / "slides"


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


# ── Public entry: slide.generate ──────────────────────────────────────────────


def slide_generate(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Generate the PPT trio for the given context.

    Returns a dict with:
      - slide_id: short identifier
      - title: the slide deck title
      - pages: number of content slides
      - outline: the structured outline (used by slide.rehearse)
      - pptx_path / pptx_url: real .pptx file
      - slidev_md_path / slidev_html_path / slidev_url: Slidev HTML preview
      - speaker_notes_md_path / speaker_notes_md_url: per-page script
      - tts_mp3_path / tts_url: optional voiceover
      - preview_doc_url / preview_doc_token / feishu_url: Feishu Docx preview
      - source: "feishu+pptx" | "pptx_only"
    """
    args = ctx.get("resolved_args") or {}
    title = (args.get("title") or "").strip()
    if not title or "{{" in title:
        title = _title_from_ctx(ctx)
    outline = args.get("outline")
    if not outline or (isinstance(outline, str) and "{{" in outline):
        outline = _build_outline_from_doc_or_intent(ctx, title)
    outline = _normalise_outline(outline)
    if len(outline) < 4:  # pad to a usable minimum
        outline = _pad_outline(outline, title)

    slide_id = f"slide_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    slide_dir = ARTIFACTS_DIR / slide_id
    _ensure_dir(slide_dir)

    # 1. Real .pptx
    pptx_path = slide_dir / f"{slide_id}.pptx"
    pages = _make_pptx(title, outline, pptx_path)
    logger.info("slide.generate: wrote pptx=%s pages=%d", pptx_path, pages)

    # 2. Slidev HTML (best-effort; markdown always emitted)
    slidev_md_path = slide_dir / f"{slide_id}.slidev.md"
    slidev_md_path.write_text(_outline_to_slidev_md(title, outline), encoding="utf-8")
    slidev_html_path = _build_slidev_html(slidev_md_path, slide_dir)

    # 3. Speaker notes markdown
    notes_md_path = slide_dir / f"{slide_id}.speaker_notes.md"
    notes_md_path.write_text(_outline_to_speaker_notes(title, outline), encoding="utf-8")

    # 4. Optional TTS mp3 (only when explicitly enabled)
    tts_mp3_path = _make_tts_optional(title, outline, slide_dir, slide_id)

    # 5. Feishu Docx preview (always good to have for mobile users)
    feishu_preview = _create_feishu_preview_doc(title, outline)

    # 6. Try uploading the .pptx to Feishu Drive
    pptx_feishu_url = _upload_pptx_to_feishu_drive(pptx_path)

    base_artifact_url = f"/artifacts/slides/{slide_id}"
    result: Dict[str, Any] = {
        "slide_id": slide_id,
        "title": title,
        "pages": pages,
        "outline": outline,
        "pptx_path": str(pptx_path),
        "pptx_url": pptx_feishu_url or f"{base_artifact_url}/{pptx_path.name}",
        "slidev_md_path": str(slidev_md_path),
        "speaker_notes_md_path": str(notes_md_path),
    }
    if slidev_html_path:
        result["slidev_html_path"] = str(slidev_html_path)
        result["slidev_url"] = f"{base_artifact_url}/index.html"
    if tts_mp3_path:
        result["tts_mp3_path"] = str(tts_mp3_path)
        result["tts_url"] = f"{base_artifact_url}/{tts_mp3_path.name}"

    if feishu_preview.get("url"):
        result["preview_doc_url"] = feishu_preview["url"]
        result["preview_doc_token"] = feishu_preview.get("doc_token", "")
        result["feishu_url"] = feishu_preview["url"]
        result["source"] = "feishu+pptx" if pptx_feishu_url else "feishu+pptx_local"
    else:
        result["source"] = "pptx_only"

    return result


def slide_rehearse(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}
    slide_id = args.get("slide_id") or ""
    outline = args.get("outline") or []

    if (not outline) and slide_id:
        # find the most recent slide artifact dir
        d = ARTIFACTS_DIR / slide_id
        for child in [d / f"{slide_id}.slidev.md"]:
            if child.exists():
                outline = _parse_slidev_md(child)
                break
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


# ── Outline derivation ────────────────────────────────────────────────────────


def _title_from_ctx(ctx: Dict[str, Any]) -> str:
    intent = (
        ctx.get("original_intent")
        or ctx.get("intent")
        or "Agent-Pilot 演示"
    )
    intent = intent.replace("\n", " ").strip()
    return intent[:30] or "Agent-Pilot 演示"


def _build_outline_from_doc_or_intent(ctx: Dict[str, Any], title: str) -> List[Dict[str, Any]]:
    """Try workforce-cached outline → LLM with doc → LLM with title → template."""
    # 0. fast path: 4-Agent workforce already produced an outline?
    workforce = ctx.get("__workforce__") or {}
    cached = workforce.get("slide_outline") or []
    if isinstance(cached, list) and len(cached) >= 4:
        logger.info("slide.outline: using 4-Agent workforce cached outline (%d pages)", len(cached))
        return _normalise_outline(cached)

    doc_md = ""
    step_results = ctx.get("step_results") or {}
    for r in step_results.values():
        if isinstance(r, dict) and r.get("markdown_content"):
            doc_md = r["markdown_content"]
            break
    intent = ctx.get("original_intent") or ctx.get("intent") or title

    outline = _llm_outline(title, intent, doc_md)
    if outline and len(outline) >= 4:
        return outline

    logger.info("slide.outline: LLM gave %d pages, padding from template", len(outline))
    return _pad_outline(outline, title)


def _llm_outline(title: str, intent: str, doc_markdown: str) -> List[Dict[str, Any]]:
    try:
        from llm.llm_client import chat, LLM_FALLBACK_MSG
    except ImportError:
        return []

    if doc_markdown:
        preview = doc_markdown[:14000]
        prompt = f"""你是一位专业的演示稿设计专家。基于以下文档内容，提炼出一份 8-12 页的高质量 PPT 大纲。

## 用户需求
{intent}

## 已有文档内容（请基于此提炼 PPT，与文档保持一致）
{preview}

请以 JSON 数组格式输出，每个元素包含 title、bullets、note 三个字段：
[
  {{"title": "封面", "bullets": ["副标题（一句话价值主张）", "演讲者：Agent-Pilot 团队"], "note": "开场白"}},
  {{"title": "目录", "bullets": ["章节1", "章节2", "章节3"], "note": "今天要讲的内容"}},
  ...
]

要求：
1. 8-12 页，结构完整，逻辑清晰
2. 每页 3-5 个 bullets，每条是一句完整有信息量的话（不是短语）
3. note 字段是这页的演讲稿（80-120 字），用于讲稿
4. 包含：封面、目录、背景与痛点、核心方案/分析（3-5 页深度展开）、案例或数据、风险与对策、总结展望、Thank You
5. PPT 内容必须与文档保持一致，是文档关键论点的提炼
6. 直接输出 JSON 数组，不要任何前缀或代码块包裹"""
    else:
        prompt = f"""你是一位专业的演示稿设计专家。请为以下主题设计一份 8-12 页的高质量 PPT 大纲。

主题：{title}
用户需求：{intent}

请以 JSON 数组格式输出，每个元素包含 title、bullets、note 三个字段：
[
  {{"title": "封面", "bullets": ["一句话价值主张", "Agent-Pilot 团队"], "note": "开场白"}},
  {{"title": "目录", "bullets": ["章节1", "章节2"], "note": "今天要讲的内容"}},
  ...
]

要求：8-12 页；每页 3-5 个完整句子的要点；note 是演讲稿（80-120 字）；
包含：封面、目录、背景与痛点、核心内容（3-5 页）、案例/数据、风险与对策、总结、Thank You。
直接输出 JSON 数组，不要任何前缀。"""

    raw = chat(prompt, temperature=0.5, max_tokens=8192)
    if not raw or raw.strip() == LLM_FALLBACK_MSG:
        return []
    arr = safe_json_parse(raw, expected_type=list, debug_label="slide.outline")
    if not arr:
        return []
    out: List[Dict[str, Any]] = []
    for i, p in enumerate(arr, 1):
        if not isinstance(p, dict):
            continue
        bullets_raw = p.get("bullets") or p.get("points") or []
        if isinstance(bullets_raw, str):
            bullets_raw = [b.strip() for b in bullets_raw.split("\n") if b.strip()]
        out.append({
            "title": str(p.get("title") or f"Slide {i}").strip(),
            "bullets": [str(b).strip() for b in bullets_raw if str(b).strip()],
            "note": str(p.get("note") or p.get("speaker_note") or "").strip(),
        })
    return out


def _pad_outline(outline: List[Dict[str, Any]], title: str) -> List[Dict[str, Any]]:
    template = [
        {"title": title, "bullets": ["AI 驱动的办公协同新范式", "Agent-Pilot 团队"], "note": "开场介绍我们的项目"},
        {"title": "目录", "bullets": ["背景与痛点", "解决方案", "技术架构", "实践案例", "未来展望"], "note": "今天要讲五个部分"},
        {"title": "背景与痛点", "bullets": [
            "知识工作者每天被 IM 打断 30+ 次，信息散落在聊天与文档中",
            "需求从对话产生，但要手动整理为方案、PPT、归档",
            "团队跨端协作时缺乏一致的进度可视化",
        ], "note": "团队协作的真实困境"},
        {"title": "解决方案", "bullets": [
            "Agent-Pilot 在飞书 IM 里主动识别任务",
            "自动驱动文档/画布/演示稿三种产物联动生成",
            "WebSocket 多端同步，移动+桌面+Web 实时一致",
        ], "note": "我们的产品定位"},
        {"title": "技术架构", "bullets": [
            "三闸门主动识别（规则+LLM+最小信息）",
            "DAG 编排 + 4-Agent 协作工坊",
            "真 .pptx / Mermaid+tldraw / Slidev 三件套",
        ], "note": "核心技术栈"},
        {"title": "实践案例", "bullets": [
            "案例一：群聊讨论 → 一句话生成方案+PPT",
            "案例二：手机扫码确认 → 桌面端编辑 PPT 实时同步",
            "案例三：模糊意图 Agent 主动澄清后再执行",
        ], "note": "真实使用场景"},
        {"title": "未来展望", "bullets": [
            "更深 AI Native：自主任务规划与持续学习",
            "更强生态：飞书白板/多维表格深度集成",
            "更广平台：iOS/Android/macOS/Windows 全端",
        ], "note": "下一步计划"},
        {"title": "Thank You", "bullets": [
            "Agent-Pilot · 让对话直接变成产物",
            "GitHub: https://github.com/bcefghj/Agent-Pilot",
            "戴尚好 / 李洁盈 · 飞书 AI 校园挑战赛",
        ], "note": "感谢评委倾听"},
    ]
    if outline:
        merged = {p["title"]: p for p in outline}
        for default in template:
            merged.setdefault(default["title"], default)
        return list(merged.values())
    return template


def _normalise_outline(outline: Any) -> List[Dict[str, Any]]:
    if not outline:
        return []
    if isinstance(outline, str):
        outline = [p.strip() for p in outline.split("\n") if p.strip()]
    out: List[Dict[str, Any]] = []
    for i, p in enumerate(outline, 1):
        if isinstance(p, dict):
            bullets_raw = p.get("bullets") or p.get("points") or []
            if isinstance(bullets_raw, str):
                bullets_raw = [b.strip() for b in bullets_raw.split("\n") if b.strip()]
            out.append({
                "title": str(p.get("title") or f"Slide {i}"),
                "bullets": [str(b) for b in bullets_raw],
                "note": str(p.get("note") or p.get("speaker_note") or ""),
            })
        elif isinstance(p, str):
            out.append({"title": p, "bullets": [], "note": ""})
    return out


# ── Real PPTX rendering ──────────────────────────────────────────────────────


# Brand colors used in the PPT template (PRD: deep navy + gold accents)
_NAVY = (0x00, 0x3D, 0x5B)
_GOLD = (0xF4, 0xA2, 0x61)
_LIGHT = (0xF5, 0xF5, 0xF5)
_WHITE = (0xFF, 0xFF, 0xFF)


def _make_pptx(title: str, outline: List[Dict[str, Any]], out_path: Path) -> int:
    """Render the outline into a real .pptx file. Returns slide count."""
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)

    blank_layout = prs.slide_layouts[6]  # Blank

    def _add_color_bar(slide, color_rgb: Tuple[int, int, int]) -> None:
        """Add a left-side color bar for visual identity."""
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.4), prs.slide_height,
        )
        bar.line.fill.background()
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor(*color_rgb)

    def _add_text(slide, left, top, width, height, text, *, font_size=18,
                  bold=False, color=(0x33, 0x33, 0x33), align="left") -> None:
        from pptx.enum.text import PP_ALIGN
        tx = slide.shapes.add_textbox(left, top, width, height)
        tf = tx.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}[align]
        run = p.add_run()
        run.text = text
        run.font.name = "Microsoft YaHei"
        run.font.size = Pt(font_size)
        run.font.bold = bold
        run.font.color.rgb = RGBColor(*color)

    def _add_bullets(slide, left, top, width, height, bullets: List[str]) -> None:
        from pptx.enum.text import PP_ALIGN
        tx = slide.shapes.add_textbox(left, top, width, height)
        tf = tx.text_frame
        tf.word_wrap = True
        for i, b in enumerate(bullets):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = PP_ALIGN.LEFT
            p.space_before = Pt(8)
            p.space_after = Pt(8)
            run = p.add_run()
            run.text = "• " + b
            run.font.name = "Microsoft YaHei"
            run.font.size = Pt(20)
            run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

    def _set_notes(slide, text: str) -> None:
        if not text:
            return
        try:
            ns = slide.notes_slide.notes_text_frame
            ns.text = text
        except Exception as e:
            logger.debug("set notes failed: %s", e)

    # Slide 1: COVER
    cover = prs.slides.add_slide(blank_layout)
    cover.background.fill.solid()
    cover.background.fill.fore_color.rgb = RGBColor(*_NAVY)
    # decorative accent bar at bottom
    accent = cover.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, 0, prs.slide_height - Inches(0.3),
        prs.slide_width, Inches(0.3),
    )
    accent.line.fill.background()
    accent.fill.solid()
    accent.fill.fore_color.rgb = RGBColor(*_GOLD)
    _add_text(cover, Inches(0.8), Inches(2.6), Inches(12), Inches(1.3),
              title, font_size=48, bold=True, color=_WHITE)
    subtitle = (outline[0].get("bullets") or [""])[0] if outline else ""
    if subtitle:
        _add_text(cover, Inches(0.8), Inches(4.0), Inches(12), Inches(0.6),
                  subtitle, font_size=22, color=_LIGHT)
    _add_text(cover, Inches(0.8), Inches(6.4), Inches(12), Inches(0.5),
              "Agent-Pilot · 飞书 AI 校园挑战赛", font_size=16, color=_GOLD)
    _set_notes(cover, outline[0].get("note", "") if outline else "开场介绍")

    # Slides 2..n: content
    content_pages = outline[1:-1] if len(outline) > 2 else outline
    for page in content_pages:
        slide = prs.slides.add_slide(blank_layout)
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor(*_WHITE)
        _add_color_bar(slide, _NAVY)
        # title
        _add_text(slide, Inches(0.8), Inches(0.5), Inches(12), Inches(0.9),
                  page.get("title", ""), font_size=32, bold=True, color=_NAVY)
        # gold underline
        underline = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(1.5), Inches(2.0), Inches(0.05),
        )
        underline.line.fill.background()
        underline.fill.solid()
        underline.fill.fore_color.rgb = RGBColor(*_GOLD)
        # bullets
        _add_bullets(slide, Inches(1.0), Inches(2.0), Inches(11.5), Inches(4.5),
                     page.get("bullets") or [])
        # footer
        _add_text(slide, Inches(0.8), Inches(7.0), Inches(12), Inches(0.3),
                  "Agent-Pilot · v13", font_size=10, color=(0x99, 0x99, 0x99))
        _set_notes(slide, page.get("note", ""))

    # Last slide: Thank You
    thank = outline[-1] if len(outline) > 1 else {"title": "Thank You", "bullets": [], "note": ""}
    last = prs.slides.add_slide(blank_layout)
    last.background.fill.solid()
    last.background.fill.fore_color.rgb = RGBColor(*_NAVY)
    _add_text(last, Inches(0.8), Inches(2.8), Inches(12), Inches(1.4),
              thank.get("title", "Thank You"),
              font_size=54, bold=True, color=_WHITE, align="center")
    extras = thank.get("bullets") or []
    if extras:
        body_text = "\n".join(extras)
        _add_text(last, Inches(0.8), Inches(4.5), Inches(12), Inches(2.0),
                  body_text, font_size=18, color=_LIGHT, align="center")
    _set_notes(last, thank.get("note", "致谢评委"))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    return len(prs.slides)


# ── Slidev export ─────────────────────────────────────────────────────────────


def _outline_to_slidev_md(title: str, outline: List[Dict[str, Any]]) -> str:
    parts = [
        "---",
        "theme: seriph",
        f"title: {title}",
        "class: text-center",
        "highlighter: shiki",
        "lineNumbers: false",
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
        if page.get("note"):
            parts.append("")
            parts.append("<!-- ")
            parts.append(page["note"])
            parts.append("-->")
        parts.append("")
    return "\n".join(parts)


def _build_slidev_html(slidev_md: Path, out_dir: Path) -> Optional[Path]:
    """Try to build Slidev HTML if `npx` is available; else skip silently."""
    npx = shutil.which("npx")
    if not npx:
        logger.info("slidev: npx not on PATH, skipping HTML build (md still saved)")
        return None
    try:
        result = subprocess.run(
            [npx, "--yes", "@slidev/cli", "build", str(slidev_md), "--out", str(out_dir)],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            logger.warning("slidev build failed: %s", result.stderr[:300])
            return None
        idx = out_dir / "index.html"
        if idx.exists():
            return idx
    except Exception as e:
        logger.warning("slidev build exception: %s", e)
    return None


# ── Speaker notes ─────────────────────────────────────────────────────────────


def _outline_to_speaker_notes(title: str, outline: List[Dict[str, Any]]) -> str:
    lines = [f"# {title} · 演讲稿\n"]
    for i, page in enumerate(outline, 1):
        lines.append(f"## 第 {i} 页：{page.get('title', '')}\n")
        note = page.get("note", "").strip()
        if note:
            lines.append(note)
        else:
            lines.append("（请用自己的语言讲 40-60 秒）")
        lines.append("")
        bullets = page.get("bullets") or []
        if bullets:
            lines.append("**幻灯片要点：**")
            for b in bullets:
                lines.append(f"- {b}")
            lines.append("")
    return "\n".join(lines)


def _speaker_note_for_page(page: Dict[str, Any]) -> str:
    if page.get("note"):
        return page["note"]
    title = page.get("title", "")
    bullets = page.get("bullets", [])
    if not bullets:
        return f"本页主题：{title}"
    return f"本页主题：{title}。要点：" + "；".join(bullets[:3]) + "。"


def _make_tts_optional(title: str, outline: List[Dict[str, Any]],
                       out_dir: Path, slide_id: str) -> Optional[Path]:
    """Best-effort TTS. Disabled by default (network dependency)."""
    if os.getenv("AGENT_PILOT_ENABLE_TTS", "0") not in ("1", "true", "yes"):
        return None
    try:
        from gtts import gTTS
    except ImportError:
        logger.info("tts: gTTS not installed, skipping mp3")
        return None
    try:
        narration = "\n".join(p.get("note") or p.get("title", "") for p in outline)
        if not narration.strip():
            return None
        mp3_path = out_dir / f"{slide_id}.mp3"
        gTTS(text=narration[:4500], lang="zh-cn").save(str(mp3_path))
        return mp3_path
    except Exception as e:
        logger.warning("tts mp3 generation failed: %s", e)
        return None


def _parse_slidev_md(path: Path) -> List[Dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return []
    pages: List[Dict[str, Any]] = []
    for chunk in raw.split("\n---\n"):
        lines = [l for l in chunk.splitlines() if l.strip()]
        if not lines:
            continue
        title = ""
        bullets: List[str] = []
        for ln in lines:
            if ln.startswith("# "):
                title = ln[2:].strip()
            elif ln.startswith("- "):
                bullets.append(ln[2:].strip())
        if title:
            pages.append({"title": title, "bullets": bullets, "note": ""})
    return pages


# ── Feishu integration ───────────────────────────────────────────────────────


def _create_feishu_preview_doc(title: str, outline: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a Feishu Docx that mirrors the deck for mobile-first viewing."""
    try:
        from config import Config
        if not (Config.FEISHU_APP_ID and Config.FEISHU_APP_SECRET):
            return {}
        import lark_oapi.api.docx.v1 as docx_api
        from bot.feishu_client import get_client

        client = get_client()
        doc_title = f"[演示稿预览] {title}"
        req = (
            docx_api.CreateDocumentRequest.builder()
            .request_body(docx_api.CreateDocumentRequestBody.builder().title(doc_title).build())
            .build()
        )
        resp = client.docx.v1.document.create(req)
        if not resp.success() or not resp.data or not resp.data.document:
            logger.warning("preview doc create failed: code=%s msg=%s",
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
            BATCH = 50
            for i in range(0, len(blocks), BATCH):
                req2 = (
                    CreateDocumentBlockChildrenRequest.builder()
                    .document_id(doc_token)
                    .block_id(doc_token)
                    .request_body(
                        CreateDocumentBlockChildrenRequestBody.builder()
                        .children(blocks[i:i + BATCH]).build()
                    ).build()
                )
                client.docx.v1.document_block_children.create(req2)
        return {"doc_token": doc_token, "url": f"https://{domain}/docx/{doc_token}"}
    except Exception as e:
        logger.warning("preview doc creation failed: %s", e)
        return {}


def _outline_to_docx_blocks(outline: List[Dict[str, Any]]) -> list:
    try:
        from lark_oapi.api.docx.v1 import Block, Text, TextElement, TextRun
    except ImportError:
        return []

    def _tb(text: str, bt: int):
        run = TextRun.builder().content(text).build()
        el = TextElement.builder().text_run(run).build()
        txt = Text.builder().elements([el]).build()
        try:
            bb = Block.builder().block_type(bt)
            if bt == 3:
                return bb.heading1(txt).build()
            if bt == 4:
                return bb.heading2(txt).build()
            if bt == 5:
                return bb.heading3(txt).build()
            if bt == 12:
                return bb.bullet(txt).build()
            return bb.text(txt).build()
        except Exception:
            return Block.builder().block_type(2).text(txt).build()

    blocks = []
    for i, page in enumerate(outline, 1):
        blocks.append(_tb(f"第 {i} 页 · {page.get('title', '')}", 3))
        for b in page.get("bullets", []) or []:
            blocks.append(_tb(b, 12))
        if page.get("note"):
            blocks.append(_tb(f"演讲稿：{page['note']}", 2))
        blocks.append(_tb("", 2))
    return blocks


def _upload_pptx_to_feishu_drive(pptx_path: Path) -> Optional[str]:
    """Upload the .pptx to Feishu Drive root folder. Returns shareable URL or None."""
    try:
        from config import Config
        if not (Config.FEISHU_APP_ID and Config.FEISHU_APP_SECRET):
            return None
        # Import lazily to avoid hard dependency at module load
        import lark_oapi as lark  # noqa: F401
        from bot.feishu_client import get_client
        from lark_oapi.api.drive.v1 import (
            UploadAllFileRequest,
            UploadAllFileRequestBody,
        )

        folder_token = os.getenv("FEISHU_FOLDER_TOKEN", "")
        client = get_client()
        with open(pptx_path, "rb") as f:
            data = f.read()
        body = (
            UploadAllFileRequestBody.builder()
            .file_name(pptx_path.name)
            .parent_type("explorer")
            .parent_node(folder_token or "")
            .size(len(data))
            .file(data)
            .build()
        )
        req = UploadAllFileRequest.builder().request_body(body).build()
        resp = client.drive.v1.file.upload_all(req)
        if not resp.success() or not resp.data:
            logger.warning("pptx upload failed: code=%s msg=%s",
                           getattr(resp, "code", "?"), getattr(resp, "msg", "?"))
            return None
        file_token = getattr(resp.data, "file_token", "") or ""
        if not file_token:
            return None
        domain = getattr(Config, "FEISHU_TENANT_DOMAIN", "") or "rcnqvnspd31b.feishu.cn"
        return f"https://{domain}/file/{file_token}"
    except Exception as e:
        logger.warning("pptx upload to drive failed: %s", e)
        return None
