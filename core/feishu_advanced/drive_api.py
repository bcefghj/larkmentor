"""Feishu Drive best-effort helpers (P2.9).

Uploads plan artifacts (PDF, PPTX, Markdown) to Feishu Drive so judges can
open them directly from the IM card. When the app lacks the ``drive:drive``
scope we fail gracefully and return ``None`` so the caller can fall back to
local file paths / dashboard URLs.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from typing import Dict, Optional

logger = logging.getLogger("feishu.drive")


def upload_all(local_path: str, *, parent_type: str = "explorer",
               parent_node: str = "", title: str = "") -> Optional[Dict[str, str]]:
    """Upload a small file (<20MB) via one-shot API.

    Returns ``{"file_token": ..., "url": ...}`` on success, ``None`` on error.
    """
    if not os.path.exists(local_path):
        return None
    size = os.path.getsize(local_path)
    if size > 20 * 1024 * 1024:
        logger.warning("drive.upload_all skip >20MB (%s bytes); use chunked", size)
        return None
    name = title or os.path.basename(local_path)
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"

    try:
        from bot.feishu_client import get_tenant_access_token
        import requests
    except Exception as e:
        logger.warning("drive.upload_all deps missing: %s", e)
        return None

    token = get_tenant_access_token()
    if not token:
        return None

    url = "https://open.feishu.cn/open-apis/drive/v1/files/upload_all"
    with open(local_path, "rb") as fh:
        files = {
            "file_name": (None, name),
            "parent_type": (None, parent_type),
            "parent_node": (None, parent_node),
            "size": (None, str(size)),
            "file": (name, fh, mime),
        }
        try:
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                files=files, timeout=60,
            )
            data = r.json() if r.content else {}
        except Exception as e:
            logger.warning("drive.upload_all http failed: %s", e)
            return None

    if (data.get("code") or 0) != 0:
        logger.warning("drive.upload_all api err: %s", (data.get("msg") or "")[:120])
        return None
    token_out = (data.get("data") or {}).get("file_token", "")
    if not token_out:
        return None
    return {
        "file_token": token_out,
        "url": f"https://bytedance.feishu.cn/file/{token_out}",
    }
