"""Feishu Attachment Handler (ShanClaw 启发)

IM 带文件 → 下载到 data/attachments/{session_id}/ → SSRF 验证 → 自动提取文本/图片并注入 agent context。
支持最多 10 files per message (100 MB each)，SSRF 保护（scheme + IP 验证）。
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger("agent.attachments")


MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_FILES_PER_MSG = 10
ALLOWED_SCHEMES = {"http", "https"}


def _is_ssrf_safe(url: str) -> bool:
    """Check URL is not pointing to internal/private network."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ALLOWED_SCHEMES:
            return False
        host = parsed.hostname or ""
        if not host:
            return False
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        except ValueError:
            # Not an IP — check hostname
            if host.lower() in ("localhost", "metadata.google.internal"):
                return False
        return True
    except Exception:
        return False


def download_attachment(
    *, url: str = "", file_key: str = "",
    session_id: str = "", max_size: int = MAX_FILE_SIZE,
) -> Dict[str, Any]:
    """Download attachment to data/attachments/{session_id}/.
    
    Supports two sources:
    1. HTTP URL (SSRF-protected)
    2. Feishu file_key (via lark-oapi download)
    """
    base_dir = Path("data/attachments") / (session_id or "default")
    base_dir.mkdir(parents=True, exist_ok=True)

    if url:
        if not _is_ssrf_safe(url):
            return {"ok": False, "error": "ssrf_blocked", "url": url}
        try:
            import requests
            r = requests.get(url, stream=True, timeout=30)
            if r.status_code != 200:
                return {"ok": False, "error": f"http_{r.status_code}"}
            total = 0
            fname = re.sub(r'[^\w\-.]', '_', urlparse(url).path.split('/')[-1] or "attachment.bin")
            out_path = base_dir / fname
            with out_path.open("wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    total += len(chunk)
                    if total > max_size:
                        f.close()
                        out_path.unlink()
                        return {"ok": False, "error": "too_large"}
                    f.write(chunk)
            return {"ok": True, "path": str(out_path), "size": total}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if file_key:
        try:
            from bot.feishu_client import get_client
            client = get_client()
            from lark_oapi.api.im.v1 import GetMessageResourceRequest
            # Simplified; actual API needs message_id + file_key
            return {"ok": False, "error": "file_key download not fully wired; use ShanClaw reference"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {"ok": False, "error": "no source"}


def extract_text(path: str) -> str:
    """Extract text from common formats: txt, md, pdf (partial), docx (partial)."""
    p = Path(path)
    if not p.exists():
        return ""
    suffix = p.suffix.lower()
    try:
        if suffix in (".txt", ".md", ".markdown", ".py", ".json", ".yaml", ".yml"):
            return p.read_text(encoding="utf-8", errors="replace")[:50_000]
        if suffix == ".pdf":
            try:
                import pypdf  # type: ignore
                reader = pypdf.PdfReader(path)
                return "\n".join((page.extract_text() or "") for page in reader.pages)[:50_000]
            except ImportError:
                return "[pdf: pypdf not installed]"
        if suffix in (".docx",):
            try:
                import docx  # type: ignore
                doc = docx.Document(path)
                return "\n".join(p.text for p in doc.paragraphs)[:50_000]
            except ImportError:
                return "[docx: python-docx not installed]"
    except Exception as e:
        return f"[extract failed: {e}]"
    return ""


def build_context_from_attachments(
    attachments: List[Dict[str, Any]], *, session_id: str = "",
) -> List[Dict[str, Any]]:
    """Process up to N attachments, returns context blocks for LLM."""
    blocks = []
    for i, att in enumerate(attachments[:MAX_FILES_PER_MSG]):
        if "url" in att:
            res = download_attachment(url=att["url"], session_id=session_id)
        elif "file_key" in att:
            res = download_attachment(file_key=att["file_key"], session_id=session_id)
        elif "path" in att:
            res = {"ok": True, "path": att["path"]}
        else:
            continue
        if not res.get("ok"):
            blocks.append({"kind": "attachment_error", "index": i, "error": res.get("error")})
            continue
        text = extract_text(res["path"])
        blocks.append({
            "kind": "attachment",
            "index": i, "path": res["path"],
            "text_preview": text[:5000],
        })
    return blocks
