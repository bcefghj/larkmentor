"""Slides Tools · Feishu OpenAPI SDK → lark-cli fallback → Marp local fallback."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

import logging

logger = logging.getLogger("agent.tools.slides")

from .registry import tool

try:
    from core.resilience import retry_with_backoff, RetryConfig
except ImportError:

    class RetryConfig:  # type: ignore[no-redef]
        def __init__(self, max_attempts=3, base_delay_sec=1.0, **kw):
            pass

    def retry_with_backoff(config=None):  # type: ignore[no-redef]
        def decorator(fn):
            return fn

        return decorator


# ---------------------------------------------------------------------------
# Custom exception hierarchy
# ---------------------------------------------------------------------------


class SlidesError(Exception):
    """Base exception for all slides-tool failures."""


class FeishuSlidesAPIError(SlidesError):
    """Feishu OpenAPI SDK call failed."""

    def __init__(self, message: str, code: str = "", log_id: str = ""):
        self.code = code
        self.log_id = log_id
        super().__init__(message)


class LarkCLIError(SlidesError):
    """lark-cli subprocess invocation failed."""


class MarpExportError(SlidesError):
    """Marp HTML export failed."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ARTIFACTS_DIR = Path("data/artifacts")


def _ensure_artifacts() -> Path:
    _ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return _ARTIFACTS_DIR


@retry_with_backoff(config=RetryConfig(max_attempts=3, base_delay_sec=1.0))
def _create_via_feishu_sdk(title: str, markdown: str, folder_token: str) -> Dict[str, Any]:
    """Primary path: create a Feishu Docx via ``lark_oapi`` and write content blocks."""
    from config import Config

    if not (Config.FEISHU_APP_ID and Config.FEISHU_APP_SECRET):
        raise FeishuSlidesAPIError("FEISHU_APP_ID / APP_SECRET not configured")

    import lark_oapi as lark  # noqa: F811
    import lark_oapi.api.docx.v1 as docx_api
    from bot.feishu_client import get_client

    client = get_client()

    req_body_builder = docx_api.CreateDocumentRequestBody.builder().title(title)
    if folder_token:
        req_body_builder = req_body_builder.folder_token(folder_token)
    req = docx_api.CreateDocumentRequest.builder().request_body(req_body_builder.build()).build()

    logger.info("feishu_sdk.create_document", title=title)
    resp = client.docx.v1.document.create(req)

    if not resp.success() or not resp.data or not resp.data.document:
        raise FeishuSlidesAPIError(
            f"CreateDocument failed: code={getattr(resp, 'code', '?')} msg={getattr(resp, 'msg', '?')}",
            code=str(getattr(resp, "code", "")),
            log_id=str(getattr(resp, "log_id", "")),
        )

    doc_token = resp.data.document.document_id
    doc_url = f"https://bytedance.feishu.cn/docx/{doc_token}"

    if markdown:
        _append_blocks_to_doc(client, doc_token, title, markdown)

    logger.info("feishu_sdk.create_document.ok", doc_token=doc_token, url=doc_url)
    return {
        "ok": True,
        "provider": "feishu_sdk",
        "doc_token": doc_token,
        "url": doc_url,
        "title": title,
    }


def _append_blocks_to_doc(
    client: Any,
    doc_token: str,
    title: str,
    markdown: str,
) -> None:
    """Best-effort: convert markdown slides into Docx blocks and append."""
    try:
        from lark_oapi.api.docx.v1 import (
            Block,
            Text,
            TextElement,
            TextRun,
            CreateDocumentBlockChildrenRequest,
            CreateDocumentBlockChildrenRequestBody,
        )

        blocks = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            run = TextRun(content=stripped.lstrip("#- *"))
            element = TextElement(text_run=run)
            txt = Text(elements=[element])
            if stripped.startswith("# "):
                blocks.append(Block(block_type=3, heading1=txt))
            elif stripped.startswith("## "):
                blocks.append(Block(block_type=4, heading2=txt))
            elif stripped.startswith("### "):
                blocks.append(Block(block_type=5, heading3=txt))
            elif stripped.startswith("- ") or stripped.startswith("* "):
                blocks.append(Block(block_type=12, bullet=txt))
            else:
                blocks.append(Block(block_type=2, text=txt))

        if not blocks:
            return

        req = (
            CreateDocumentBlockChildrenRequest.builder()
            .document_id(doc_token)
            .block_id(doc_token)
            .request_body(CreateDocumentBlockChildrenRequestBody.builder().children(blocks).build())
            .build()
        )
        resp = client.docx.v1.document_block_children.create(req)
        if not resp.success():
            logger.warning(
                "feishu_sdk.append_blocks.partial_fail",
                code=getattr(resp, "code", "?"),
                msg=getattr(resp, "msg", "?"),
            )
    except Exception as exc:
        logger.debug("feishu_sdk.append_blocks.skip", error=str(exc))


def _create_via_lark_cli(title: str, markdown: str) -> Dict[str, Any]:
    """Secondary path: shell out to ``lark-cli slides create``."""
    if not shutil.which("lark-cli"):
        raise LarkCLIError("lark-cli not found on PATH")

    try:
        result = subprocess.run(
            ["lark-cli", "slides", "create", "--title", title, "--markdown", markdown[:10_000]],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise LarkCLIError(f"lark-cli timed out after 60s") from exc
    except FileNotFoundError as exc:
        raise LarkCLIError("lark-cli binary not executable") from exc

    if result.returncode != 0:
        raise LarkCLIError(f"lark-cli exited {result.returncode}: {result.stderr[:300]}")

    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        data = {"raw": result.stdout.strip()}

    logger.info("lark_cli.create.ok", data_keys=list(data.keys()))
    return {"ok": True, "provider": "lark-cli", **data}


def _create_via_marp(title: str, markdown: str) -> Dict[str, Any]:
    """Tertiary path: generate Marp-compatible markdown and optionally export HTML."""
    artifacts = _ensure_artifacts()
    ts = int(time.time())
    md_path = artifacts / f"slides-{ts}.md"
    html_path = artifacts / f"slides-{ts}.html"

    marp_md = f"---\nmarp: true\ntheme: gaia\npaginate: true\n---\n\n# {title}\n\n{markdown}\n"
    md_path.write_text(marp_md, encoding="utf-8")
    logger.info("marp.markdown_saved", path=str(md_path))

    if shutil.which("marp"):
        try:
            subprocess.run(
                ["marp", str(md_path), "-o", str(html_path), "--html"],
                check=True,
                capture_output=True,
                timeout=60,
            )
            logger.info("marp.html_exported", path=str(html_path))
            return {
                "ok": True,
                "provider": "marp",
                "md_path": str(md_path),
                "html_path": str(html_path),
                "url": f"file://{html_path}",
            }
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise MarpExportError(f"marp export failed: {exc}") from exc

    return {
        "ok": True,
        "provider": "markdown-only",
        "md_path": str(md_path),
        "note": "marp not installed; run `npm i -g @marp-team/marp-cli`",
    }


# ---------------------------------------------------------------------------
# Public tool: slides.create
# ---------------------------------------------------------------------------


@tool(
    name="slides.create",
    description="创建演示稿（优先飞书 Docx API → lark-cli → Marp 本地 HTML）",
    permission="write",
    team="any",
)
def create_slides(
    title: str = "",
    markdown: str = "",
    folder_token: str = "",
) -> Dict[str, Any]:
    # 1. Feishu OpenAPI SDK (with retry)
    try:
        return _create_via_feishu_sdk(title, markdown, folder_token)
    except (FeishuSlidesAPIError, ImportError, Exception) as exc:
        logger.warning("slides.create.feishu_sdk_failed", error=str(exc))

    # 2. lark-cli subprocess
    try:
        return _create_via_lark_cli(title, markdown)
    except LarkCLIError as exc:
        logger.warning("slides.create.lark_cli_failed", error=str(exc))

    # 3. Marp local fallback
    try:
        return _create_via_marp(title, markdown)
    except MarpExportError as exc:
        logger.warning("slides.create.marp_export_failed", error=str(exc))
        # Marp binary failed but markdown was saved — still return md-only result
        artifacts = _ensure_artifacts()
        md_candidates = sorted(artifacts.glob("slides-*.md"), reverse=True)
        if md_candidates:
            return {
                "ok": True,
                "provider": "markdown-only",
                "md_path": str(md_candidates[0]),
                "note": "marp export failed; markdown saved",
            }
    except SlidesError as exc:
        logger.error("slides.create.all_failed", error=str(exc))

    return {"ok": False, "error": "all slide creation strategies exhausted"}


# ---------------------------------------------------------------------------
# Public tool: slides.rehearse
# ---------------------------------------------------------------------------


@tool(
    name="slides.rehearse",
    description="为演示稿生成讲稿（每页的口述台本 + 语气标记 + 预计时长）",
    permission="readonly",
    team="any",
)
def rehearse_slides(markdown: str = "") -> Dict[str, Any]:
    try:
        from ..providers import default_providers

        prompt = (
            "Generate a Chinese speech rehearsal script for these slides.\n\n"
            f"Slides (markdown):\n{markdown[:6000]}\n\n"
            "For each slide:\n"
            "- 1-2 sentence hook\n"
            "- 3-5 key talking points\n"
            "- tone tag (excited/serious/pause)\n"
            "- estimated seconds (8-45)\n\n"
            "Output plain markdown."
        )
        script = default_providers().chat(
            messages=[{"role": "user", "content": prompt}],
            task_kind="chinese_chat",
            max_tokens=2500,
        )
        logger.info("slides.rehearse.ok", script_len=len(script))
        return {"ok": True, "script": script}
    except Exception as exc:
        logger.error("slides.rehearse.failed", error=str(exc))
        return {"ok": False, "error": str(exc)}
