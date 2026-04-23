"""archive.bundle tool – Scenario F (summary & delivery).

Collects every artifact produced during the run (Doc / Canvas / Slide /
transcripts) and writes a manifest JSON + a single Feishu Docx summary.
Returns a share URL the Bot can post back to the IM thread.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List

logger = logging.getLogger("pilot.tool.archive")

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "data", "pilot_artifacts",
)


def archive_bundle(step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    os.makedirs(DATA_DIR, exist_ok=True)
    plan_id = ctx.get("plan_id", f"plan_{int(time.time())}")
    step_results: Dict[str, Dict[str, Any]] = ctx.get("step_results") or {}

    artifacts: List[Dict[str, Any]] = []
    for sid, r in step_results.items():
        if not isinstance(r, dict):
            continue
        item = {"step_id": sid}
        for key in ("doc_token", "url", "canvas_id", "slide_id",
                    "pptx_url", "pdf_url", "title", "markdown_path"):
            if r.get(key):
                item[key] = r[key]
        if len(item) > 1:
            artifacts.append(item)

    manifest = {
        "plan_id": plan_id,
        "user_open_id": ctx.get("user_open_id", ""),
        "bundled_ts": int(time.time()),
        "artifacts": artifacts,
        "share_url_hint": f"/pilot/{plan_id}",
    }
    manifest_path = os.path.join(DATA_DIR, f"{plan_id}.manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # Attempt to produce a Feishu Docx summary
    summary_doc_url = _try_create_summary_doc(plan_id, manifest)

    share_url = summary_doc_url or f"file://{manifest_path}"

    return {
        "plan_id": plan_id,
        "share_url": share_url,
        "manifest_path": manifest_path,
        "artifact_count": len(artifacts),
    }


def _try_create_summary_doc(plan_id: str, manifest: Dict[str, Any]) -> str:
    try:
        from .doc_tool import _try_create_feishu_doc, _try_append_feishu_blocks
        title = f"[Agent-Pilot] 汇报摘要 · {plan_id}"
        created = _try_create_feishu_doc(title)
        if not created or not created.get("doc_token"):
            return ""
        md = _manifest_to_markdown(manifest)
        _try_append_feishu_blocks(created["doc_token"], md)
        return created.get("url", "")
    except Exception as e:
        logger.debug("archive summary doc skipped: %s", e)
        return ""


def _manifest_to_markdown(manifest: Dict[str, Any]) -> str:
    lines = ["# Agent-Pilot 汇报摘要", "",
             f"Plan id: `{manifest['plan_id']}`",
             f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(manifest['bundled_ts']))}",
             "", "## 产物列表"]
    for a in manifest["artifacts"]:
        title = a.get("title") or a.get("step_id")
        url = a.get("url") or a.get("pptx_url") or a.get("markdown_path") or "-"
        lines.append(f"- [{title}]({url})")
    lines += ["", "## 下一步",
              "- 评审会建议 5/7 前召开",
              "- 如需二次编辑，请在任意一端修改，所有端通过 CRDT 自动同步"]
    return "\n".join(lines)
