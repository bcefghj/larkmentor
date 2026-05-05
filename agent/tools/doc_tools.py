"""Doc Tools · 飞书文档 CRUD（Feishu Docx OpenAPI + structured fallbacks）."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import structlog

    logger = structlog.get_logger("agent.tools.doc")
except ImportError:
    import logging

    logger = logging.getLogger("agent.tools.doc")

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


class DocToolError(Exception):
    """Base exception for doc-tool operations."""


class FeishuDocAPIError(DocToolError):
    """Feishu Docx OpenAPI call returned an error response."""

    def __init__(self, message: str, code: str = "", log_id: str = ""):
        self.code = code
        self.log_id = log_id
        super().__init__(message)


class FeishuTokenError(DocToolError):
    """Token refresh or authentication failed."""


class DocNotFoundError(DocToolError):
    """Requested doc_token does not exist or is inaccessible."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_ARTIFACTS_DIR = Path("data/pilot_artifacts")


def _ensure_artifacts() -> Path:
    _ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return _ARTIFACTS_DIR


def _get_feishu_client():
    """Obtain a configured ``lark_oapi.Client``, refreshing token if needed."""
    from config import Config

    if not (Config.FEISHU_APP_ID and Config.FEISHU_APP_SECRET):
        raise FeishuTokenError("FEISHU_APP_ID / APP_SECRET not configured")
    from bot.feishu_client import get_client

    return get_client()


def _save_local_markdown(title: str, markdown: str) -> Dict[str, Any]:
    """Write to local filesystem when Feishu API is unreachable."""
    artifacts = _ensure_artifacts()
    filename = f"doc-{int(time.time())}-{uuid.uuid4().hex[:6]}.md"
    path = artifacts / filename
    path.write_text(f"# {title}\n\n{markdown}", encoding="utf-8")
    logger.info("doc.local_fallback.saved", path=str(path))
    return {
        "ok": True,
        "local_path": str(path),
        "doc_token": "",
        "url": f"file://{path}",
        "note": "feishu API unavailable, saved locally",
    }


# ---------------------------------------------------------------------------
# doc.create
# ---------------------------------------------------------------------------


@retry_with_backoff(config=RetryConfig(max_attempts=3, base_delay_sec=1.0))
def _create_doc_via_sdk(title: str, folder_token: str) -> Dict[str, Any]:
    """Create a new Feishu Docx document via ``lark_oapi``."""
    import lark_oapi.api.docx.v1 as docx_api

    client = _get_feishu_client()

    req_body_builder = docx_api.CreateDocumentRequestBody.builder().title(title)
    if folder_token:
        req_body_builder = req_body_builder.folder_token(folder_token)
    req = docx_api.CreateDocumentRequest.builder().request_body(req_body_builder.build()).build()

    logger.info("feishu_sdk.doc.create", title=title, folder_token=folder_token or "(root)")
    resp = client.docx.v1.document.create(req)

    if not resp.success() or not resp.data or not resp.data.document:
        raise FeishuDocAPIError(
            f"CreateDocument failed: code={getattr(resp, 'code', '?')} msg={getattr(resp, 'msg', '?')}",
            code=str(getattr(resp, "code", "")),
            log_id=str(getattr(resp, "log_id", "")),
        )

    doc_token = resp.data.document.document_id
    url = f"https://bytedance.feishu.cn/docx/{doc_token}"
    logger.info("feishu_sdk.doc.create.ok", doc_token=doc_token, url=url)
    return {"ok": True, "doc_token": doc_token, "url": url, "title": title}


@tool(
    name="doc.create",
    description="创建一个飞书文档（Markdown 内容）；返回 doc_token + URL",
    permission="write",
    team="any",
)
def create_doc(
    title: str = "",
    markdown: str = "",
    folder_token: str = "",
) -> Dict[str, Any]:
    # 1. Try Feishu Docx API (with retry)
    try:
        result = _create_doc_via_sdk(title, folder_token)
        if markdown and result.get("doc_token"):
            _append_blocks(result["doc_token"], markdown)
        return result
    except (FeishuDocAPIError, FeishuTokenError) as exc:
        logger.warning("doc.create.sdk_failed", error=str(exc), code=getattr(exc, "code", ""))
    except ImportError as exc:
        logger.warning("doc.create.sdk_unavailable", error=str(exc))
    except Exception as exc:
        logger.warning("doc.create.sdk_unexpected", error=str(exc), exc_type=type(exc).__name__)

    # 2. Try core.agent_pilot.tools.doc_tool (legacy integration)
    try:
        from core.agent_pilot.tools.doc_tool import create_docx

        result = create_docx(title=title, markdown=markdown, folder_token=folder_token)
        logger.info("doc.create.legacy_ok")
        return {"ok": True, **result}
    except Exception as exc:
        logger.debug("doc.create.legacy_failed", error=str(exc))

    # 3. Local markdown fallback
    return _save_local_markdown(title, markdown)


# ---------------------------------------------------------------------------
# doc.update
# ---------------------------------------------------------------------------


@retry_with_backoff(config=RetryConfig(max_attempts=3, base_delay_sec=1.0))
def _update_doc_via_sdk(doc_token: str, markdown: str, mode: str) -> Dict[str, Any]:
    """Append or replace blocks in an existing Feishu Docx document."""
    client = _get_feishu_client()

    if mode == "replace":
        _clear_document_blocks(client, doc_token)

    blocks_added = _append_blocks(doc_token, markdown)

    logger.info("feishu_sdk.doc.update.ok", doc_token=doc_token, mode=mode, blocks=blocks_added)
    return {"ok": True, "doc_token": doc_token, "blocks_added": blocks_added, "mode": mode}


def _clear_document_blocks(client: Any, doc_token: str) -> None:
    """Best-effort: delete all children of the root block before replacing."""
    try:
        from lark_oapi.api.docx.v1 import ListDocumentBlockRequest

        req = ListDocumentBlockRequest.builder().document_id(doc_token).build()
        resp = client.docx.v1.document_block.list(req)
        if resp.success() and resp.data and resp.data.items:
            from lark_oapi.api.docx.v1 import BatchDeleteDocumentBlockChildrenRequest

            block_ids = [b.block_id for b in resp.data.items if hasattr(b, "block_id") and b.block_id != doc_token]
            if block_ids:
                del_req = (
                    BatchDeleteDocumentBlockChildrenRequest.builder()
                    .document_id(doc_token)
                    .block_id(doc_token)
                    .start_index(0)
                    .end_index(len(block_ids))
                    .build()
                )
                client.docx.v1.document_block_children.batch_delete(del_req)
    except Exception as exc:
        logger.debug("doc.clear_blocks.skip", error=str(exc))


def _append_blocks(doc_token: str, markdown: str) -> int:
    """Convert markdown lines to Feishu Docx blocks and append to document."""
    try:
        from lark_oapi.api.docx.v1 import (
            Block,
            Text,
            TextElement,
            TextRun,
            CreateDocumentBlockChildrenRequest,
            CreateDocumentBlockChildrenRequestBody,
        )

        client = _get_feishu_client()

        blocks = _markdown_to_blocks(markdown)
        if not blocks:
            return 0

        req = (
            CreateDocumentBlockChildrenRequest.builder()
            .document_id(doc_token)
            .block_id(doc_token)
            .request_body(CreateDocumentBlockChildrenRequestBody.builder().children(blocks).build())
            .build()
        )
        resp = client.docx.v1.document_block_children.create(req)
        if resp.success():
            return len(blocks)

        logger.warning(
            "doc.append_blocks.api_error",
            code=getattr(resp, "code", "?"),
            msg=getattr(resp, "msg", "?"),
        )
        return 0
    except Exception as exc:
        logger.debug("doc.append_blocks.skip", error=str(exc))
        return 0


def _markdown_to_blocks(md: str) -> list:
    """Minimal markdown → Feishu Docx Block list."""
    try:
        from lark_oapi.api.docx.v1 import Block, Text, TextElement, TextRun
    except ImportError:
        return []

    blocks = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line:
            continue

        def _text_block(text: str, block_type: int) -> Any:
            run = TextRun(content=text)
            element = TextElement(text_run=run)
            txt = Text(elements=[element])
            try:
                if block_type == 3:
                    return Block(block_type=block_type, heading1=txt)
                if block_type == 4:
                    return Block(block_type=block_type, heading2=txt)
                if block_type == 5:
                    return Block(block_type=block_type, heading3=txt)
                if block_type == 12:
                    return Block(block_type=block_type, bullet=txt)
                return Block(block_type=block_type, text=txt)
            except Exception:
                return Block(block_type=2, text=txt)

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


@tool(
    name="doc.update",
    description="更新飞书文档（追加或替换内容）",
    permission="write",
    team="any",
)
def update_doc(
    doc_token: str = "",
    markdown: str = "",
    mode: str = "append",
) -> Dict[str, Any]:
    # 1. Feishu SDK (with retry)
    try:
        return _update_doc_via_sdk(doc_token, markdown, mode)
    except (FeishuDocAPIError, FeishuTokenError) as exc:
        logger.warning("doc.update.sdk_failed", error=str(exc))
    except ImportError as exc:
        logger.warning("doc.update.sdk_unavailable", error=str(exc))
    except Exception as exc:
        logger.warning("doc.update.sdk_unexpected", error=str(exc), exc_type=type(exc).__name__)

    # 2. Legacy integration
    try:
        from core.agent_pilot.tools.doc_tool import update_docx

        result = update_docx(doc_token=doc_token, markdown=markdown, mode=mode)
        return {"ok": True, **result}
    except Exception as exc:
        logger.debug("doc.update.legacy_failed", error=str(exc))

    return {"ok": False, "error": "all update strategies failed"}


# ---------------------------------------------------------------------------
# doc.get
# ---------------------------------------------------------------------------


@retry_with_backoff(config=RetryConfig(max_attempts=2, base_delay_sec=0.5))
def _get_doc_via_sdk(doc_token: str) -> Dict[str, Any]:
    """Fetch raw content of a Feishu Docx document."""
    from lark_oapi.api.docx.v1 import RawContentDocumentRequest

    client = _get_feishu_client()
    req = RawContentDocumentRequest.builder().document_id(doc_token).build()

    logger.info("feishu_sdk.doc.get", doc_token=doc_token)
    resp = client.docx.v1.document.raw_content(req)

    if not resp.success():
        raise FeishuDocAPIError(
            f"RawContent failed: code={getattr(resp, 'code', '?')}",
            code=str(getattr(resp, "code", "")),
        )

    content = getattr(resp.data, "content", "") if resp.data else ""
    return {"ok": True, "content": content, "doc_token": doc_token}


@tool(
    name="doc.get",
    description="读取飞书文档的 raw Markdown 内容",
    permission="readonly",
    team="any",
)
def get_doc(doc_token: str = "") -> Dict[str, Any]:
    if not doc_token:
        return {"ok": False, "error": "doc_token is required"}

    # 1. SDK
    try:
        return _get_doc_via_sdk(doc_token)
    except (FeishuDocAPIError, FeishuTokenError) as exc:
        logger.warning("doc.get.sdk_failed", error=str(exc))
    except ImportError as exc:
        logger.warning("doc.get.sdk_unavailable", error=str(exc))
    except Exception as exc:
        logger.warning("doc.get.sdk_unexpected", error=str(exc), exc_type=type(exc).__name__)

    # 2. Legacy
    try:
        from core.agent_pilot.tools.doc_tool import fetch_docx

        content = fetch_docx(doc_token=doc_token)
        return {"ok": True, "content": content, "doc_token": doc_token}
    except Exception as exc:
        logger.debug("doc.get.legacy_failed", error=str(exc))

    return {"ok": False, "error": f"could not fetch document {doc_token}"}


# ---------------------------------------------------------------------------
# doc.search
# ---------------------------------------------------------------------------


@retry_with_backoff(config=RetryConfig(max_attempts=2, base_delay_sec=0.5))
def _search_via_sdk(query: str, limit: int) -> Dict[str, Any]:
    """Search Feishu Drive/Wiki for documents matching *query*."""
    from bot.feishu_client import get_tenant_access_token
    import json
    import urllib.request

    token = get_tenant_access_token()
    if not token:
        raise FeishuTokenError("tenant_access_token unavailable")

    url = (
        f"https://open.feishu.cn/open-apis/suite/docs-api/search/object"
        f"?search_key={urllib.request.quote(query)}&count={limit}&offset=0"
        f"&owner_ids=&docs_types=doc,docx,sheet,wiki"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    docs = body.get("data", {}).get("docs_entities", [])
    results = [
        {
            "title": d.get("title", ""),
            "doc_token": d.get("docs_token", ""),
            "url": d.get("url", ""),
            "type": d.get("docs_type", ""),
        }
        for d in docs
    ]
    logger.info("feishu_sdk.doc.search.ok", query=query, results=len(results))
    return {"ok": True, "results": results}


@tool(
    name="doc.search",
    description="在飞书 Drive/Wiki 中搜索文档",
    permission="readonly",
    team="any",
)
def search_doc(query: str = "", limit: int = 5) -> Dict[str, Any]:
    if not query:
        return {"ok": False, "error": "query is required", "results": []}

    # 1. SDK / HTTP search
    try:
        return _search_via_sdk(query, limit)
    except (FeishuDocAPIError, FeishuTokenError) as exc:
        logger.warning("doc.search.sdk_failed", error=str(exc))
    except Exception as exc:
        logger.warning("doc.search.sdk_unexpected", error=str(exc), exc_type=type(exc).__name__)

    # 2. Legacy wiki_search
    try:
        from core.feishu_advanced.wiki_search import wiki_search

        results = wiki_search(query, page_size=limit)
        return {"ok": True, "results": results or []}
    except Exception as exc:
        logger.debug("doc.search.legacy_failed", error=str(exc))

    return {"ok": False, "error": "all search strategies failed", "results": []}


# ---------------------------------------------------------------------------
# doc.insert_image
# ---------------------------------------------------------------------------


@tool(
    name="doc.insert_image",
    description="往飞书文档插入图片 URL 或本地路径",
    permission="write",
    team="any",
)
def insert_image(
    doc_token: str = "",
    image_path: str = "",
    caption: str = "",
) -> Dict[str, Any]:
    if not doc_token:
        return {"ok": False, "error": "doc_token is required"}

    # 1. SDK upload + insert
    try:
        return _insert_image_via_sdk(doc_token, image_path, caption)
    except (FeishuDocAPIError, FeishuTokenError, DocToolError) as exc:
        logger.warning("doc.insert_image.sdk_failed", error=str(exc))
    except ImportError as exc:
        logger.warning("doc.insert_image.sdk_unavailable", error=str(exc))
    except Exception as exc:
        logger.warning("doc.insert_image.sdk_unexpected", error=str(exc), exc_type=type(exc).__name__)

    # 2. Legacy
    try:
        from core.agent_pilot.tools.doc_tool import insert_image as _insert

        result = _insert(doc_token=doc_token, image_path=image_path, caption=caption)
        return {"ok": True, **result}
    except Exception as exc:
        logger.debug("doc.insert_image.legacy_failed", error=str(exc))

    return {"ok": False, "error": "image insertion failed"}


@retry_with_backoff(config=RetryConfig(max_attempts=2, base_delay_sec=1.0))
def _insert_image_via_sdk(doc_token: str, image_path: str, caption: str) -> Dict[str, Any]:
    """Upload an image to Feishu and insert it into a Docx document."""
    import os
    from bot.feishu_client import get_tenant_access_token
    import json
    import urllib.request

    token = get_tenant_access_token()
    if not token:
        raise FeishuTokenError("tenant_access_token unavailable for image upload")

    if not os.path.isfile(image_path):
        raise DocToolError(f"image file not found: {image_path}")

    # Upload image via Drive media API
    import mimetypes

    mime = mimetypes.guess_type(image_path)[0] or "image/png"
    file_name = os.path.basename(image_path)

    # Use multipart upload
    boundary = uuid.uuid4().hex
    with open(image_path, "rb") as f:
        file_data = f.read()

    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image_type"\r\n\r\nmessage\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{file_name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
        + file_data
        + f"\r\n--{boundary}--\r\n".encode()
    )

    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/images",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        upload_resp = json.loads(resp.read().decode("utf-8"))

    image_key = upload_resp.get("data", {}).get("image_key", "")
    if not image_key:
        raise FeishuDocAPIError("image upload returned no image_key")

    logger.info("doc.insert_image.uploaded", image_key=image_key, doc_token=doc_token)

    if caption:
        _append_blocks(doc_token, f"*{caption}*")

    return {"ok": True, "doc_token": doc_token, "image_key": image_key}


# ---------------------------------------------------------------------------
# doc.insert_table
# ---------------------------------------------------------------------------


@tool(
    name="doc.insert_table",
    description="往飞书文档插入表格（Markdown 表格语法或二维列表）",
    permission="write",
    team="any",
)
def insert_table(
    doc_token: str = "",
    rows: Optional[List[List[str]]] = None,
    markdown_table: str = "",
) -> Dict[str, Any]:
    if not doc_token:
        return {"ok": False, "error": "doc_token is required"}

    # 1. SDK
    try:
        return _insert_table_via_sdk(doc_token, rows, markdown_table)
    except (FeishuDocAPIError, FeishuTokenError, DocToolError) as exc:
        logger.warning("doc.insert_table.sdk_failed", error=str(exc))
    except ImportError as exc:
        logger.warning("doc.insert_table.sdk_unavailable", error=str(exc))
    except Exception as exc:
        logger.warning("doc.insert_table.sdk_unexpected", error=str(exc), exc_type=type(exc).__name__)

    # 2. Legacy
    try:
        from core.agent_pilot.tools.doc_tool import insert_table as _insert

        result = _insert(doc_token=doc_token, rows=rows, markdown_table=markdown_table)
        return {"ok": True, **result}
    except Exception as exc:
        logger.debug("doc.insert_table.legacy_failed", error=str(exc))

    return {"ok": False, "error": "table insertion failed"}


@retry_with_backoff(config=RetryConfig(max_attempts=2, base_delay_sec=1.0))
def _insert_table_via_sdk(
    doc_token: str,
    rows: Optional[List[List[str]]],
    markdown_table: str,
) -> Dict[str, Any]:
    """Insert a table into a Feishu Docx document via the blocks API."""
    if markdown_table and not rows:
        rows = _parse_markdown_table(markdown_table)
    if not rows:
        raise DocToolError("no table data provided (rows or markdown_table required)")

    from lark_oapi.api.docx.v1 import (
        CreateDocumentBlockChildrenRequest,
        CreateDocumentBlockChildrenRequestBody,
        Block,
    )

    client = _get_feishu_client()

    n_rows = len(rows)
    n_cols = max((len(r) for r in rows), default=0)
    table_block = Block(
        block_type=23,
        table={
            "property": {"row_size": n_rows, "column_size": n_cols},
            "cells": [cell for row in rows for cell in row],
        },
    )

    req = (
        CreateDocumentBlockChildrenRequest.builder()
        .document_id(doc_token)
        .block_id(doc_token)
        .request_body(CreateDocumentBlockChildrenRequestBody.builder().children([table_block]).build())
        .build()
    )
    resp = client.docx.v1.document_block_children.create(req)
    if not resp.success():
        raise FeishuDocAPIError(
            f"InsertTable failed: code={getattr(resp, 'code', '?')}",
            code=str(getattr(resp, "code", "")),
        )

    logger.info("doc.insert_table.ok", doc_token=doc_token, rows=n_rows, cols=n_cols)
    return {"ok": True, "doc_token": doc_token, "rows": n_rows, "cols": n_cols}


def _parse_markdown_table(md: str) -> List[List[str]]:
    """Parse a simple markdown table string into a 2D list of strings."""
    rows = []
    for line in md.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("|---") or line.startswith("| ---"):
            continue
        if set(line.replace("|", "").replace("-", "").strip()) == set():
            continue
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if cells:
            rows.append(cells)
    return rows
