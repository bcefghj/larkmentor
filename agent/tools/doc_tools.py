"""Doc Tools · 飞书文档 CRUD（真走飞书 Docx API）。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .registry import tool

logger = logging.getLogger("agent.tools.doc")


@tool(
    name="doc.create",
    description="创建一个飞书文档（Markdown 内容）；返回 doc_token + URL",
    permission="write",
    team="any",
)
def create_doc(title: str = "", markdown: str = "", folder_token: str = "") -> Dict[str, Any]:
    try:
        from core.agent_pilot.tools.doc_tool import create_docx
        result = create_docx(title=title, markdown=markdown, folder_token=folder_token)
        return {"ok": True, **result}
    except Exception as e:
        # Fallback: just write to local artifacts
        logger.warning("doc.create fallback to local: %s", e)
        from pathlib import Path
        import uuid, time
        artifacts = Path.cwd() / "data" / "pilot_artifacts" / f"doc-{int(time.time())}-{uuid.uuid4().hex[:6]}.md"
        artifacts.parent.mkdir(parents=True, exist_ok=True)
        artifacts.write_text(f"# {title}\n\n{markdown}", encoding="utf-8")
        return {
            "ok": True, "local_path": str(artifacts),
            "doc_token": "", "url": f"file://{artifacts}",
            "note": "feishu docx API failed, saved locally",
            "error": str(e),
        }


@tool(
    name="doc.update",
    description="更新飞书文档（追加或替换内容）",
    permission="write",
    team="any",
)
def update_doc(doc_token: str = "", markdown: str = "", mode: str = "append") -> Dict[str, Any]:
    try:
        from core.agent_pilot.tools.doc_tool import update_docx
        result = update_docx(doc_token=doc_token, markdown=markdown, mode=mode)
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="doc.get",
    description="读取飞书文档的 raw Markdown 内容",
    permission="readonly",
    team="any",
)
def get_doc(doc_token: str = "") -> Dict[str, Any]:
    try:
        from core.agent_pilot.tools.doc_tool import fetch_docx
        content = fetch_docx(doc_token=doc_token)
        return {"ok": True, "content": content, "doc_token": doc_token}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="doc.search",
    description="在飞书 Drive/Wiki 中搜索文档",
    permission="readonly",
    team="any",
)
def search_doc(query: str = "", limit: int = 5) -> Dict[str, Any]:
    try:
        from core.feishu_advanced.wiki_search import wiki_search
        results = wiki_search(query, page_size=limit)
        return {"ok": True, "results": results or []}
    except Exception as e:
        return {"ok": False, "error": str(e), "results": []}


@tool(
    name="doc.insert_image",
    description="往飞书文档插入图片 URL 或本地路径",
    permission="write",
    team="any",
)
def insert_image(doc_token: str = "", image_path: str = "", caption: str = "") -> Dict[str, Any]:
    try:
        from core.agent_pilot.tools.doc_tool import insert_image as _insert
        result = _insert(doc_token=doc_token, image_path=image_path, caption=caption)
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="doc.insert_table",
    description="往飞书文档插入表格（Markdown 表格语法或二维列表）",
    permission="write",
    team="any",
)
def insert_table(doc_token: str = "", rows: Optional[List[List[str]]] = None, markdown_table: str = "") -> Dict[str, Any]:
    try:
        from core.agent_pilot.tools.doc_tool import insert_table as _insert
        result = _insert(doc_token=doc_token, rows=rows, markdown_table=markdown_table)
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}
