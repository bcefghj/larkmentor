"""BuilderAgent — 写入飞书 Docx / 组装 PPTX.

根据 state["task_type"] 决定产出形态：
  - doc:  创建飞书 Docx 并写入内容
  - ppt:  用 python-pptx 渲染 .pptx
  - trio: doc + ppt + 归档

产出结果写入 state["artifacts"]。
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from pilot.agents.base import AgentState, BaseAgent

logger = logging.getLogger("pilot.agents.builder")

_BUILDER_SYSTEM_PROMPT = """\
你是 Agent-Pilot 的构建员，负责将草稿内容写入飞书文档或生成 PPTX 文件。
你的工作是忠实地将已审核通过的内容转化为最终产物。
"""


class BuilderAgent(BaseAgent):
    """构建 Agent：将审核通过的草稿写入飞书 Docx 或生成 PPTX。"""

    name = "builder_agent"
    role = "构建员"
    system_prompt = _BUILDER_SYSTEM_PROMPT

    async def execute(self, state: AgentState) -> AgentState:
        task_type = state.get("task_type", "doc")
        draft_sections = state.get("draft_sections", [])
        outline = state.get("outline", [])
        intent = state.get("intent", "")
        title = state.get("_title", intent[:60] or "Agent-Pilot 文档")  # type: ignore[typeddict-item]

        artifacts: list[dict[str, Any]] = state.get("artifacts", [])

        if task_type in ("doc", "trio"):
            doc_artifact = await self._build_doc(title, draft_sections, state)
            artifacts.append(doc_artifact)

        if task_type in ("ppt", "trio"):
            ppt_artifact = await self._build_ppt(title, outline, draft_sections, state)
            artifacts.append(ppt_artifact)

        if task_type == "trio":
            archive_artifact = self._build_archive(title, artifacts)
            artifacts.append(archive_artifact)

        state["artifacts"] = artifacts
        logger.info("BuilderAgent: %d artifacts built for task_type=%s", len(artifacts), task_type)
        return state

    async def _build_doc(
        self,
        title: str,
        draft_sections: list[dict[str, Any]],
        state: AgentState,
    ) -> dict[str, Any]:
        """创建飞书 Docx 并写入草稿内容。"""
        from pilot.capability.tools.doc import doc_create, doc_append

        full_md = "\n\n".join(
            s.get("content", "") for s in draft_sections if isinstance(s, dict)
        )

        ctx = {
            "session": None,
            "chat_id": state.get("chat_id", ""),
            "step_id": f"builder_{int(time.time())}",
        }

        create_result = await doc_create(
            title=title,
            folder_token=os.getenv("FEISHU_FOLDER_TOKEN", ""),
            _ctx=ctx,
        )
        doc_token = create_result.get("doc_token", "")

        append_result = await doc_append(
            doc_token=doc_token,
            markdown=full_md,
            intent=state.get("intent", ""),
            _ctx=ctx,
        )

        return {
            "type": "doc",
            "title": title,
            "doc_token": doc_token,
            "url": create_result.get("url", ""),
            "source": create_result.get("source", "local"),
            "wrote_blocks": append_result.get("wrote_blocks", 0),
            "markdown_chars": len(full_md),
        }

    async def _build_ppt(
        self,
        title: str,
        outline: list[dict[str, Any]],
        draft_sections: list[dict[str, Any]],
        state: AgentState,
    ) -> dict[str, Any]:
        """用 python-pptx 生成演示文稿。"""
        from pilot.capability.tools.slide import slide_generate

        ppt_outline = self._outline_to_ppt_format(outline, draft_sections)

        ctx = {
            "session": None,
            "chat_id": state.get("chat_id", ""),
            "step_id": f"builder_ppt_{int(time.time())}",
        }

        result = await slide_generate(
            title=title,
            outline=ppt_outline,
            intent=state.get("intent", ""),
            pages=max(8, len(outline) + 2),
            _ctx=ctx,
        )

        pptx_url = result.get("pptx_url_absolute") or result.get("pptx_url", "")

        if state.get("chat_id") and os.getenv("FEISHU_FOLDER_TOKEN"):
            pptx_path = result.get("pptx_path", "")
            if pptx_path and Path(pptx_path).exists():
                try:
                    from pilot.surface.feishu.client import get_feishu_client
                    upload = await get_feishu_client().drive_upload_file(local_path=pptx_path)
                    if upload:
                        result["drive_upload"] = upload
                except Exception as e:
                    logger.warning("PPT drive upload failed: %s", e)

        return {
            "type": "ppt",
            "title": title,
            "slide_id": result.get("slide_id", ""),
            "pages": result.get("pages", 0),
            "pptx_url": pptx_url,
            "pptx_path": result.get("pptx_path", ""),
        }

    @staticmethod
    def _outline_to_ppt_format(
        outline: list[dict[str, Any]],
        draft_sections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """将 planner 大纲 + writer 草稿转换为 slide.generate 期望的格式。"""
        ppt_pages: list[dict[str, Any]] = []

        section_map: dict[str, str] = {}
        for s in draft_sections:
            if isinstance(s, dict):
                section_map[s.get("heading", "")] = s.get("content", "")

        for i, section in enumerate(outline):
            if not isinstance(section, dict):
                continue
            heading = section.get("heading", "")
            key_points = section.get("key_points", [])

            if i == 0:
                template = "Hero"
            elif i == len(outline) - 1:
                template = "Hero"
            elif len(key_points) >= 4:
                template = "Cards"
            elif len(key_points) == 2:
                template = "TwoColumn"
            else:
                template = "List"

            content = section_map.get(heading, "")
            notes = content[:300] if content else ""

            ppt_pages.append({
                "template": template,
                "title": heading[:60],
                "bullets": [str(p)[:120] for p in key_points[:5]],
                "notes": notes,
            })

        return ppt_pages

    @staticmethod
    def _build_archive(title: str, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        """trio 模式：创建归档记录。"""
        return {
            "type": "archive",
            "title": f"{title} · 三件套归档",
            "items": [
                {"type": a.get("type", ""), "url": a.get("url", "") or a.get("pptx_url", "")}
                for a in artifacts
            ],
            "created_at": int(time.time()),
        }
