"""canvas.create + canvas.add_shape tools.

We keep the canvas model offline by default:

* `canvas.create` creates a local JSON file under ``data/pilot_artifacts/``
  that represents a tldraw scene. The web/mobile client can load it over
  the sync WebSocket and render with tldraw.
* `canvas.add_shape` mutates that JSON and broadcasts the change via the
  CRDT hub. When the Feishu Board API is enabled we additionally mirror
  the shape to Feishu's native whiteboard (best-effort, never blocks).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pilot.tool.canvas")

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "data", "pilot_artifacts",
)


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def canvas_create(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}
    title = args.get("title") or f"Canvas {ctx.get('plan_id', '')}"

    _ensure_dir()
    canvas_id = f"canvas_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    path = os.path.join(DATA_DIR, f"{canvas_id}.json")
    scene = {
        "canvas_id": canvas_id,
        "title": title,
        "created_ts": int(time.time()),
        "shapes": [],
        "version": 1,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scene, f, ensure_ascii=False, indent=2)

    # Mirror to Feishu Board (best-effort)
    feishu_url = _try_create_feishu_board(title)

    _broadcast(ctx, {
        "type": "canvas.created",
        "canvas_id": canvas_id,
        "title": title,
        "url": feishu_url or f"/artifacts/{canvas_id}.json",
    })

    return {
        "canvas_id": canvas_id,
        "url": feishu_url or f"/artifacts/{canvas_id}.json",
        "title": title,
        "local_path": path,
    }


def canvas_add_shape(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = ctx.get("resolved_args") or {}
    canvas_id = args.get("canvas_id") or ""
    shape_type = args.get("shape_type") or "rect"
    text = args.get("text") or ""

    def _f(v, default):
        """Tolerant float parser. LLM Planners sometimes emit placeholder
        strings like '{{auto}}' or '自动' – we coerce those to the default."""
        if v is None:
            return float(default)
        try:
            return float(v)
        except (TypeError, ValueError):
            return float(default)

    x = _f(args.get("x"), 100)
    y = _f(args.get("y"), 100)
    w = _f(args.get("w"), 200)
    h = _f(args.get("h"), 80)

    path = os.path.join(DATA_DIR, f"{canvas_id}.json")
    if not canvas_id or not os.path.exists(path):
        # Auto-seed a demo frame if planner asked for add_shape without create
        logger.debug("canvas.add_shape: no canvas %s, seeding demo frame", canvas_id)
        seeded = canvas_create(step, ctx)
        canvas_id = seeded["canvas_id"]
        path = os.path.join(DATA_DIR, f"{canvas_id}.json")

    with open(path, "r", encoding="utf-8") as f:
        scene = json.load(f)

    shape_id = f"s_{uuid.uuid4().hex[:8]}"
    shape = {
        "id": shape_id,
        "type": shape_type,
        "x": x, "y": y, "w": w, "h": h,
        "text": text,
        "ts": int(time.time()),
    }
    # Rich media support (good-to-have category)
    if shape_type == "image":
        shape["src"] = args.get("src") or ""
        shape["alt"] = args.get("alt") or text
    elif shape_type == "table":
        rows = args.get("rows") or [[""]]
        shape["rows"] = rows
        shape["cols"] = max(len(r) for r in rows) if rows else 1
    elif shape_type == "sticky":
        shape["color"] = args.get("color") or "#FFD93D"
    scene["shapes"].append(shape)
    # Demo seed: if this is first shape and user asked for "frame", add 3 connected nodes
    if shape_type == "frame" and len(scene["shapes"]) == 1:
        scene["shapes"].extend([
            {"id": f"s_{uuid.uuid4().hex[:8]}", "type": "node",
             "x": 160, "y": 120, "w": 160, "h": 60, "text": "输入", "ts": int(time.time())},
            {"id": f"s_{uuid.uuid4().hex[:8]}", "type": "node",
             "x": 400, "y": 120, "w": 160, "h": 60, "text": "Agent Planner", "ts": int(time.time())},
            {"id": f"s_{uuid.uuid4().hex[:8]}", "type": "node",
             "x": 640, "y": 120, "w": 160, "h": 60, "text": "Doc / Canvas / PPT", "ts": int(time.time())},
            {"id": f"arrow_{uuid.uuid4().hex[:8]}", "type": "arrow",
             "x": 320, "y": 150, "w": 80, "h": 1, "text": "", "ts": int(time.time())},
            {"id": f"arrow_{uuid.uuid4().hex[:8]}", "type": "arrow",
             "x": 560, "y": 150, "w": 80, "h": 1, "text": "", "ts": int(time.time())},
        ])
    scene["version"] += 1

    with open(path, "w", encoding="utf-8") as f:
        json.dump(scene, f, ensure_ascii=False, indent=2)

    _broadcast(ctx, {
        "type": "canvas.shape_added",
        "canvas_id": canvas_id,
        "shape": shape,
        "version": scene["version"],
    })

    return {"canvas_id": canvas_id, "shape_id": shape_id, "total_shapes": len(scene["shapes"])}


# ── Feishu Board (best-effort, P1.3 upgrade) ──


def _try_create_feishu_board(title: str) -> Optional[str]:
    """Attempt to create a Feishu Board whiteboard via Open API.

    Tries three paths in order:
      1. ``core.feishu_advanced.board_api.create_board`` (our wrapper)
      2. Raw HTTP call to ``https://open.feishu.cn/open-apis/board/v1/whiteboards``
      3. None (fall back to local tldraw scene)

    All failures are swallowed; the tldraw scene remains the source of truth.
    """
    try:
        try:
            from core.feishu_advanced.board_api import create_board as _cb  # type: ignore
            url = _cb(title=title)
            if url:
                return url
        except Exception:
            pass

        from config import Config
        if not (Config.FEISHU_APP_ID and Config.FEISHU_APP_SECRET):
            return None
        # HTTP path: requires board:whiteboard scope. Best-effort only.
        from bot.feishu_client import get_tenant_access_token  # type: ignore
        tat = get_tenant_access_token()
        if not tat:
            return None
        import json as _json
        import urllib.request, urllib.error
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/board/v1/whiteboards",
            data=_json.dumps({"name": title}).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {tat}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                body = _json.loads(r.read().decode("utf-8"))
                token = ((body.get("data") or {}).get("whiteboard") or {}).get("whiteboard_id")
                if token:
                    return f"https://www.feishu.cn/board/{token}"
        except urllib.error.HTTPError as herr:
            logger.debug("feishu board http error %s", herr.code)
        return None
    except Exception as e:
        logger.debug("feishu board create skipped: %s", e)
        return None


def _broadcast(ctx: Dict[str, Any], payload: Dict[str, Any]) -> None:
    try:
        from core.sync.crdt_hub import broadcast_state
        broadcast_state(ctx.get("plan_id", ""), payload)
    except Exception as e:
        logger.debug("canvas broadcast skipped: %s", e)
