"""Generator Agent — Sprint 一次一个，写完自评再交 QA.

Cognition 教训：所有"写"动作都由这个单线程 Generator 串行做，
避免多个 Agent 并行写出风格冲突。
"""

from __future__ import annotations

import logging
from typing import Any

from pilot.capability.workforce.sprint_contract import SprintContract

logger = logging.getLogger("pilot.workforce.generator")


class GeneratorAgent:
    """单线程 Writer."""

    async def propose_contract(
        self,
        *,
        sprint: dict[str, Any],
        spec_title: str,
        sprint_index: int = 0,
    ) -> SprintContract:
        """给 Evaluator 看的提案：我准备做什么 + 完成标准."""
        contract = SprintContract(
            title=sprint.get("title", ""),
            goal=sprint.get("goal", ""),
            sprint_index=sprint_index,
        )
        # 默认提案模板
        title = sprint.get("title", "")
        if "文档" in title or "方案" in title or "doc" in title.lower():
            contract.proposed_implementation = (
                f"调用 doc.create + doc.append 生成完整方案文档（≥1500 字）"
            )
            contract.deliverables = ["doc_token", "url", "字数 ≥ 1500"]
            contract.test_criteria = [
                "文档可正常打开",
                "至少 5 个二级标题",
                "包含数据/案例/风险",
            ]
        elif "画布" in title or "架构" in title or "canvas" in title.lower():
            contract.proposed_implementation = "调用 canvas.create 生成 tldraw + Mermaid"
            contract.deliverables = ["canvas_id", "tldraw_url", "mermaid 代码"]
            contract.test_criteria = [
                "至少 4 个节点 + 3 条箭头",
                "Mermaid 代码可在飞书 Docx 中渲染",
                "节点标签为中文",
            ]
        elif "ppt" in title.lower() or "演示" in title or "幻灯" in title:
            contract.proposed_implementation = "调用 slide.generate 生成 6+ 页 .pptx + 演讲稿"
            contract.deliverables = ["slide_id", "pptx_url", "speaker_notes_md_url"]
            contract.test_criteria = [
                "PPT 至少 6 页",
                "每页有标题 + 要点 + 演讲备注",
                "封面用 Hero 模板，结尾用 Hero 模板",
            ]
        elif "归档" in title or "archive" in title.lower():
            contract.proposed_implementation = "调用 archive.bundle 汇总产物"
            contract.deliverables = ["share_url", "summary_md", "items"]
            contract.test_criteria = [
                "summary 包含全部产物链接",
                "share_url 可访问",
            ]
        else:
            contract.proposed_implementation = f"执行 {title}"
            contract.deliverables = ["输出 dict"]
            contract.test_criteria = ["返回 ok=True"]

        return contract

    async def execute(
        self,
        *,
        contract: SprintContract,
        tool_executor,
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """根据合约执行该 sprint."""
        logger.info("generator executing sprint %s: %s", contract.sprint_index, contract.title)
        # 真正的工具调度交给上层 Orchestrator；这里只是占位
        return {
            "sprint_id": contract.sprint_id,
            "title": contract.title,
            "executed": True,
        }
