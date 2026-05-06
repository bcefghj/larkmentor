"""archive.bundle — 汇总产物 + 生成分享链接."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from pilot.context.filesystem_memory import FilesystemMemory

logger = logging.getLogger("pilot.tool.archive")


def register_to(reg) -> None:
    reg.register(
        "archive.bundle",
        description="汇总文档/画布/PPT 等产物，生成 markdown 摘要 + 分享链接",
        input_schema={
            "type": "object",
            "properties": {
                "artifacts": {"type": "array", "description": "可选，留空则自动从上游 step_results 收集"},
                "title": {"type": "string"},
            },
        },
        read_only=False,
        namespace="pilot",
    )(archive_bundle)


async def archive_bundle(
    *,
    artifacts: list | None = None,
    title: str = "",
    _ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    items = list(artifacts or [])
    if not items and _ctx:
        items = _collect_from_steps(_ctx.get("step_results") or {})

    md_lines = [f"# {title or '[Agent-Pilot] 任务交付'}\n", f"_生成时间: {time.strftime('%Y-%m-%d %H:%M')}_", ""]
    for it in items:
        kind = it.get("kind", "artifact")
        url = it.get("url") or it.get("uri") or ""
        ttl = it.get("title", "")
        md_lines.append(f"- **{kind}** {ttl}：[{url}]({url})")

    summary_md = "\n".join(md_lines)

    session_id = ""
    if _ctx and _ctx.get("session"):
        try:
            session_id = _ctx["session"].session_id
        except Exception:
            pass
    mem = FilesystemMemory(session_id=session_id)
    summary_art = mem.store_text(
        summary_md,
        kind="archive",
        mime_type="text/markdown",
        summary=title or "Agent-Pilot 任务交付",
        tool="archive.bundle",
        step_id=(_ctx or {}).get("step_id", ""),
    )

    return {
        "title": title or "[Agent-Pilot] 任务交付",
        "share_url": summary_art.uri,  # 本地 artifact:// URL；服务器可代理为 /artifacts/...
        "items": items,
        "items_count": len(items),
        "summary_md": summary_md,
        "summary_artifact": summary_art.to_dict(),
        "ok": True,
    }


def _collect_from_steps(step_results: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for sid, r in step_results.items():
        if not isinstance(r, dict):
            continue
        if "doc_token" in r and ("url" in r or "source" in r):
            items.append({
                "kind": "doc",
                "title": r.get("title", "文档"),
                "url": r.get("url", ""),
            })
        if "canvas_id" in r:
            items.append({
                "kind": "canvas",
                "title": r.get("title", "画布"),
                "url": r.get("tldraw_url") or r.get("mermaid_url", ""),
            })
        if "slide_id" in r and r.get("pptx_url"):
            items.append({
                "kind": "slide",
                "title": r.get("title", "演示稿"),
                "url": r["pptx_url"],
            })
    return items
