"""Slides Tools · lark-slides CLI + Marp fallback."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .registry import tool

logger = logging.getLogger("agent.tools.slides")


@tool(
    name="slides.create",
    description="创建一个演示稿（优先走 lark-slides CLI Skill，备用 Marp 生成 HTML）",
    permission="write",
    team="any",
)
def create_slides(title: str = "", markdown: str = "", folder_token: str = "") -> Dict[str, Any]:
    # 1. Try lark-cli slides create
    try:
        import shutil
        if shutil.which("lark-cli"):
            result = subprocess.run(
                ["lark-cli", "slides", "create", "--title", title, "--markdown", markdown[:10000]],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                try:
                    import json
                    data = json.loads(result.stdout)
                    return {"ok": True, "provider": "lark-cli", **data}
                except Exception:
                    return {"ok": True, "provider": "lark-cli", "raw": result.stdout}
    except Exception as e:
        logger.debug("lark-cli slides failed: %s", e)

    # 2. Try existing slide_tool
    try:
        from core.agent_pilot.tools.slide_tool import create_slides as _create
        result = _create(title=title, markdown=markdown)
        return {"ok": True, "provider": "slide_tool", **(result or {})}
    except Exception as e:
        logger.debug("core slide_tool failed: %s", e)

    # 3. Marp fallback (generate HTML)
    try:
        artifacts_dir = Path("data/artifacts")
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        md_path = artifacts_dir / f"slides-{ts}.md"
        html_path = artifacts_dir / f"slides-{ts}.html"
        # Marp-compatible header
        marp_md = f"""---
marp: true
theme: gaia
paginate: true
---

# {title}

{markdown}
"""
        md_path.write_text(marp_md, encoding="utf-8")
        # Try marp-cli
        import shutil as _sh
        if _sh.which("marp"):
            subprocess.run(
                ["marp", str(md_path), "-o", str(html_path), "--html"],
                check=True, capture_output=True, timeout=60,
            )
            return {
                "ok": True, "provider": "marp",
                "md_path": str(md_path), "html_path": str(html_path),
                "url": f"file://{html_path}",
            }
        return {
            "ok": True, "provider": "markdown-only",
            "md_path": str(md_path),
            "note": "marp not installed, markdown saved (npm install -g @marp-team/marp-cli)",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


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
            f"Generate a Chinese speech rehearsal script for these slides.\n\n"
            f"Slides (markdown):\n{markdown[:6000]}\n\n"
            f"For each slide:\n"
            f"- 1-2 sentence hook\n"
            f"- 3-5 key talking points\n"
            f"- tone tag (excited/serious/pause)\n"
            f"- estimated seconds (8-45)\n\n"
            f"Output plain markdown."
        )
        script = default_providers().chat(
            messages=[{"role": "user", "content": prompt}],
            task_kind="chinese_chat",
            max_tokens=2500,
        )
        return {"ok": True, "script": script}
    except Exception as e:
        return {"ok": False, "error": str(e)}
