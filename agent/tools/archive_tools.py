"""Archive Tools · Wiki 归档 + Drive 上传 + HMAC 分享链接。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .registry import tool

logger = logging.getLogger("agent.tools.archive")


@tool(
    name="archive.wiki",
    description="把内容归档到飞书 Wiki 节点",
    permission="write",
    team="any",
)
def archive_to_wiki(
    title: str = "", content: str = "",
    wiki_space_token: str = "", parent_node_token: str = "",
) -> Dict[str, Any]:
    try:
        from core.agent_pilot.tools.archive_tool import archive_to_wiki as _archive
        result = _archive(title=title, content=content,
                          wiki_space_token=wiki_space_token,
                          parent_node_token=parent_node_token)
        return {"ok": True, **(result or {})}
    except Exception as e:
        # Fallback: save local
        artifacts = Path("data/artifacts") / f"archive-{int(time.time())}.md"
        artifacts.parent.mkdir(parents=True, exist_ok=True)
        artifacts.write_text(f"# {title}\n\n{content}", encoding="utf-8")
        return {"ok": True, "local_path": str(artifacts), "note": "wiki api failed, saved local", "error": str(e)}


@tool(
    name="archive.drive_upload",
    description="上传文件到飞书 Drive，返回文件 token",
    permission="write",
    team="any",
)
def drive_upload(file_path: str = "", parent_folder_token: str = "") -> Dict[str, Any]:
    try:
        from core.feishu_advanced.drive_api import upload_all
        result = upload_all(file_path=file_path, parent_folder_token=parent_folder_token)
        return {"ok": True, **(result or {})}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="archive.share_link",
    description="生成 HMAC 签名的分享链接（默认 7 天过期）",
    permission="readonly",
    team="any",
)
def share_link(plan_id: str = "", ttl_sec: int = 7 * 86400) -> Dict[str, Any]:
    try:
        from core.agent_pilot.share_sig import sign_url
        base = os.getenv("LARKMENTOR_DASHBOARD_URL", "")
        path = f"{base}/pilot/{plan_id}" if base else f"/pilot/{plan_id}"
        result = sign_url(plan_id, base_path=path, ttl_sec=ttl_sec)
        return {"ok": True, **(result or {})}
    except Exception as e:
        # Manual fallback
        secret = os.getenv("LARKMENTOR_PILOT_SHARE_SECRET", "")
        if secret:
            exp = int(time.time()) + ttl_sec
            msg = f"{plan_id}|{exp}".encode()
            mac = hmac.new(secret.encode(), msg, hashlib.sha256).digest()
            sig = base64.urlsafe_b64encode(mac).decode().rstrip("=")
            return {"ok": True, "plan_id": plan_id, "signed": True, "url": f"/pilot/{plan_id}?sig={sig}.{exp}", "exp_ts": exp}
        return {"ok": False, "error": str(e)}
