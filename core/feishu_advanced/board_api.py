"""Feishu Whiteboard (Board) API best-effort wrapper.

Scope requirement: ``board:whiteboard`` + ``board:whiteboard:node``.
Graceful degradation: every error returns a falsey value so the caller
can fall back to the local tldraw scene.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("flowguard.feishu.board")

API_BASE = "https://open.feishu.cn/open-apis"


def _post(path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        from bot.feishu_client import get_tenant_access_token  # type: ignore
        tat = get_tenant_access_token()
        if not tat:
            return None
        req = urllib.request.Request(
            API_BASE + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {tat}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as herr:
        try:
            body = herr.read().decode("utf-8")
        except Exception:
            body = ""
        logger.debug("board HTTP %s: %s", herr.code, body[:200])
        return None
    except Exception as exc:
        logger.debug("board request failed: %s", exc)
        return None


def create_board(*, title: str) -> str:
    """Returns the shareable URL on success, empty string otherwise."""
    body = _post("/board/v1/whiteboards", {"name": title or "LarkMentor Canvas"})
    if not body or body.get("code", -1) != 0:
        return ""
    wb = (body.get("data") or {}).get("whiteboard") or {}
    wid = wb.get("whiteboard_id") or wb.get("id") or ""
    if not wid:
        return ""
    return f"https://www.feishu.cn/board/{wid}"


def add_node(*, whiteboard_id: str, shape_type: str, text: str = "",
             x: float = 100, y: float = 100, w: float = 200, h: float = 80) -> str:
    """Insert a simple node into the whiteboard. Returns node_id or ''."""
    body = _post(f"/board/v1/whiteboards/{whiteboard_id}/nodes", {
        "type": shape_type or "rectangle",
        "text": text,
        "x": x, "y": y, "width": w, "height": h,
    })
    if not body or body.get("code", -1) != 0:
        return ""
    return ((body.get("data") or {}).get("node") or {}).get("node_id", "")
