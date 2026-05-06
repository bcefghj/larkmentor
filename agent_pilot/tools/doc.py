"""doc.create + doc.append – v13.

Improvements over v12:
- Always populates ``markdown_content`` in the result dict so downstream
  ``slide.generate`` / ``canvas.create`` can derive consistent content.
- Single-shot generation by default (per user request "no chapter expansion"),
  with one automatic retry at higher temperature if the first call returns a
  too-short or fallback string.
- Markdown → Feishu Docx blocks converter handles batched writes (50 at a
  time, since the OpenAPI hard-caps each request).
- Local fallback writes ``data/pilot_artifacts/{doc_token}.md`` so demos run
  even without Feishu credentials.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List

logger = logging.getLogger("agent_pilot.tool.doc")

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "pilot_artifacts",
)


def _ensure_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


# ── Public ────────────────────────────────────────────────────────────────────


def doc_create(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}
    title = args.get("title") or f"[Agent-Pilot] {ctx.get('plan_id', '')}"

    real = _try_create_feishu_doc(title)
    if real:
        logger.info("doc.create via Feishu API ok token=%s", real.get("doc_token"))
        return real

    _ensure_dir()
    doc_token = f"local_doc_{int(time.time())}"
    path = os.path.join(DATA_DIR, f"{doc_token}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n_由 Agent-Pilot 自动生成_\n")
    return {
        "doc_token": doc_token,
        "url": f"file://{path}",
        "title": title,
        "fallback": "local_markdown",
    }


def doc_append(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}
    doc_token = args.get("doc_token") or ""
    if not doc_token or doc_token.startswith("$") or doc_token.startswith("{"):
        # Resolve from previous step results
        for sid, r in (ctx.get("step_results") or {}).items():
            if isinstance(r, dict) and r.get("doc_token") and r.get("source") == "feishu":
                doc_token = r["doc_token"]
                logger.info("doc.append: resolved doc_token=%s from step %s", doc_token, sid)
                break

    if not doc_token:
        logger.error("doc.append: no doc_token available, cannot append")
        return {"error": "no doc_token", "blocks_added": 0, "markdown_content": ""}

    markdown = args.get("markdown") or ""
    if not markdown or (isinstance(markdown, str) and "{{" in markdown):
        logger.info("doc.append: no markdown provided, generating via LLM")
        markdown = _generate_document(ctx)

    if not markdown:
        logger.error("doc.append: LLM generation returned empty content")
        return {
            "doc_token": doc_token,
            "blocks_added": 0,
            "markdown_content": "",
            "error": "content_generation_failed",
        }

    logger.info("doc.append: generated %d chars of markdown for doc %s",
                len(markdown), doc_token)

    if doc_token and not doc_token.startswith("local_doc_"):
        added = _try_append_feishu_blocks(doc_token, markdown)
        if added:
            return {
                "doc_token": doc_token,
                "blocks_added": added,
                "markdown_content": markdown,
                "source": "feishu",
            }
        # Real Feishu doc but append failed – still return content for downstream
        return {
            "doc_token": doc_token,
            "blocks_added": 0,
            "markdown_content": markdown,
            "source": "feishu_append_failed",
        }

    _ensure_dir()
    path = os.path.join(DATA_DIR, f"{doc_token}.md")
    if not os.path.exists(path):
        path = os.path.join(DATA_DIR, f"local_doc_{int(time.time())}.md")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n\n" + markdown + "\n")
    return {
        "doc_token": doc_token,
        "blocks_added": markdown.count("\n") + 1,
        "markdown_content": markdown,
        "source": "local_markdown",
        "path": path,
    }


# ── Feishu integration ────────────────────────────────────────────────────────


def _try_create_feishu_doc(title: str) -> Dict[str, Any]:
    try:
        from config import Config

        if not (Config.FEISHU_APP_ID and Config.FEISHU_APP_SECRET):
            return {}
        import lark_oapi.api.docx.v1 as docx_api
        from bot.feishu_client import get_client

        client = get_client()
        req = (
            docx_api.CreateDocumentRequest.builder()
            .request_body(docx_api.CreateDocumentRequestBody.builder().title(title).build())
            .build()
        )
        resp = client.docx.v1.document.create(req)
        if not resp.success() or not resp.data or not resp.data.document:
            logger.warning("doc.create feishu api failed code=%s msg=%s",
                           getattr(resp, "code", "?"), getattr(resp, "msg", "?"))
            return {}
        doc_token = resp.data.document.document_id
        domain = getattr(Config, "FEISHU_TENANT_DOMAIN", "") or "rcnqvnspd31b.feishu.cn"
        return {
            "doc_token": doc_token,
            "url": f"https://{domain}/docx/{doc_token}",
            "title": title,
            "source": "feishu",
        }
    except Exception as e:
        logger.debug("doc.create feishu fallback: %s", e)
        return {}


def _try_append_feishu_blocks(doc_token: str, markdown: str) -> int:
    """Convert markdown to Feishu Docx blocks and append. Returns block count."""
    try:
        from lark_oapi.api.docx.v1 import (
            CreateDocumentBlockChildrenRequest,
            CreateDocumentBlockChildrenRequestBody,
        )
        from bot.feishu_client import get_client

        client = get_client()
        blocks = _markdown_to_blocks(markdown)
        if not blocks:
            logger.warning("doc.append: 0 blocks for %d chars", len(markdown))
            return 0

        BATCH_SIZE = 50
        total = 0
        for i in range(0, len(blocks), BATCH_SIZE):
            batch = blocks[i:i + BATCH_SIZE]
            logger.info("doc.append: batch %d-%d / %d to %s",
                        i + 1, i + len(batch), len(blocks), doc_token)
            req = (
                CreateDocumentBlockChildrenRequest.builder()
                .document_id(doc_token)
                .block_id(doc_token)
                .request_body(
                    CreateDocumentBlockChildrenRequestBody.builder()
                    .children(batch).build()
                ).build()
            )
            resp = client.docx.v1.document_block_children.create(req)
            if resp.success():
                total += len(batch)
            else:
                logger.warning("doc.append feishu batch failed code=%s msg=%s",
                               getattr(resp, "code", "?"), getattr(resp, "msg", "?"))
                break

        if total > 0:
            logger.info("doc.append: wrote %d/%d blocks to %s", total, len(blocks), doc_token)
        return total
    except Exception as e:
        logger.warning("doc.append feishu exception: %s", e)
        return 0


def _markdown_to_blocks(md: str) -> List[Any]:
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

    blocks: List[Any] = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("### "):
            blocks.append(_tb(line[4:], 5))
        elif line.startswith("## "):
            blocks.append(_tb(line[3:], 4))
        elif line.startswith("# "):
            blocks.append(_tb(line[2:], 3))
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append(_tb(line[2:], 12))
        else:
            blocks.append(_tb(line, 2))
    return blocks


# ── LLM generation (single-shot with one retry) ──────────────────────────────


def _generate_document(ctx: Dict[str, Any]) -> str:
    intent = (
        ctx.get("original_intent", "")
        or ctx.get("intent", "")
        or ctx.get("description", "")
        or ctx.get("plan_id", "")
    )
    step_results = ctx.get("step_results") or {}

    thread_context = ""
    for sid, result in step_results.items():
        if isinstance(result, dict) and "messages" in result:
            thread_context = "\n".join(
                f"- {m.get('sender', '?')}: {m.get('text', '')[:100]}"
                for m in result["messages"][-8:]
            )
            break

    try:
        from llm.llm_client import chat, LLM_FALLBACK_MSG
    except ImportError:
        logger.error("doc generation: cannot import llm_client")
        return _static_fallback(intent or ctx.get("plan_id", ""))

    base_prompt = f"""你是一位资深专业文档撰写专家。请根据以下需求，直接生成一份完整、详尽、专业的 Markdown 文档。

## 用户需求
{intent}

{"## 参考上下文" + chr(10) + thread_context if thread_context else ""}

## 文档结构要求
请包含以下部分（根据主题灵活调整）：
1. 概述与摘要 — 文档目标、核心结论
2. 背景分析 — 行业现状、发展脉络、相关数据
3. 核心内容（2-3 个深度章节）— 技术/业务分析、关键趋势、方案比较
4. 实践案例 — 具体应用、成功经验、行业先行者
5. 风险与挑战 — 潜在问题、应对策略
6. 结论与展望 — 总结要点、未来方向

## 格式要求
- 用 ## 作为章节大标题，### 作为子标题
- 用 - 作为列表项
- 每个章节写 3-5 段充实内容，有分析、有数据、有案例
- 总字数不少于 1500 字
- 语言流畅专业，逻辑清晰
- 直接输出 Markdown 内容，不要用代码块包裹
- 不要输出"以下是文档"之类的前缀，直接从 ## 开始"""

    logger.info("doc generation: calling LLM for intent='%s'", intent[:60])
    t0 = time.time()
    try:
        result = chat(base_prompt, temperature=0.5)
        elapsed = time.time() - t0
        logger.info("doc generation: LLM returned %d chars in %.1fs",
                    len(result) if result else 0, elapsed)

        if result and result.strip() != LLM_FALLBACK_MSG and len(result.strip()) >= 600:
            return _strip_wrapping(result)

        # Retry once at higher temperature with a stricter instruction
        logger.warning("doc generation: short/empty result (%d chars), retrying",
                       len(result) if result else 0)
        retry_prompt = base_prompt + "\n\n请确保正文超过 1500 字，结构完整。"
        result2 = chat(retry_prompt, temperature=0.7)
        if result2 and result2.strip() != LLM_FALLBACK_MSG and len(result2.strip()) >= 400:
            return _strip_wrapping(result2)
    except Exception as e:
        logger.error("doc generation failed: %s", e, exc_info=True)

    return _static_fallback(intent or ctx.get("plan_id", ""))


def _strip_wrapping(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        m = re.search(r"```(?:markdown)?\s*([\s\S]+?)```", content)
        if m:
            content = m.group(1).strip()
    return content


def _static_fallback(intent: str) -> str:
    return (
        f"## 概述\n\n本文围绕「{intent}」展开，由 Agent-Pilot 自动生成。\n\n"
        "## 背景分析\n\n（LLM 接口暂时不可用，此处为占位文本，请稍后重试或在飞书直接编辑。）\n\n"
        "## 下一步行动\n\n- [ ] 明确验收标准\n- [ ] 指派负责人\n- [ ] 安排评审会议"
    )
