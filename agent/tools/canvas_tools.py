"""Canvas Tools · 飞书画板 + Mermaid 渲染 + Yjs CRDT ops。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .registry import tool

logger = logging.getLogger("agent.tools.canvas")


@tool(
    name="canvas.create_board",
    description="创建一块飞书画板，返回 board_token + URL",
    permission="write",
    team="any",
)
def create_board(title: str = "") -> Dict[str, Any]:
    try:
        from core.feishu_advanced.board_api import create_board as _create
        return {"ok": True, **(_create(title=title) or {})}
    except Exception as e:
        logger.debug("create_board fallback: %s", e)
        return {"ok": False, "error": str(e), "note": "Board API needs permission"}


@tool(
    name="canvas.add_node",
    description="往画板加节点（flowchart / rect / sticky / image）",
    permission="write",
    team="any",
)
def add_node(
    board_token: str = "", kind: str = "rect",
    text: str = "", x: int = 0, y: int = 0,
    width: int = 160, height: int = 80,
) -> Dict[str, Any]:
    try:
        from core.feishu_advanced.board_api import add_node as _add
        return {"ok": True, **(_add(board_token, kind=kind, text=text, x=x, y=y, width=width, height=height) or {})}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="canvas.render_mermaid",
    description="把 Mermaid DSL 渲染成 PNG（通过 lark-whiteboard skill 或 mmdc）",
    permission="write",
    team="any",
)
def render_mermaid(dsl: str = "", output_path: str = "") -> Dict[str, Any]:
    """输出 PNG 路径，可用于 doc.insert_image."""
    try:
        import subprocess, tempfile, time
        out_path = output_path or str(Path("data/artifacts") / f"mermaid-{int(time.time())}.png")
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".mmd", mode="w", delete=False, encoding="utf-8") as f:
            f.write(dsl)
            mmd_path = f.name
        # Try mmdc (mermaid-cli)
        try:
            subprocess.run(
                ["mmdc", "-i", mmd_path, "-o", out_path, "-w", "1200", "-H", "800"],
                check=True, capture_output=True, timeout=60,
            )
            return {"ok": True, "png_path": out_path, "dsl": dsl[:200]}
        except FileNotFoundError:
            return {"ok": False, "error": "mmdc not installed", "note": "pip install nothing; npm install -g @mermaid-js/mermaid-cli", "dsl": dsl[:200]}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="canvas.yjs_op",
    description="推送 CRDT 操作到 sync server（tldraw 真协同）",
    permission="write",
    team="any",
)
def yjs_op(room_id: str = "", op_kind: str = "add", payload: Optional[Dict] = None) -> Dict[str, Any]:
    """Send CRDT update to sync service."""
    try:
        import requests
        sync_url = os.getenv("LARKMENTOR_SYNC_URL", "http://127.0.0.1:8002/yjs/op")
        r = requests.post(
            sync_url,
            json={"room_id": room_id, "kind": op_kind, "payload": payload or {}},
            timeout=5,
        )
        return {"ok": r.status_code == 200, "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}
