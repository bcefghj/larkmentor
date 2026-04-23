"""Bitable AI Agent Node · 飞书独家 2026 特性

多维表格某字段改行 → Webhook → agent/loop.run → 回写 AI 字段。

使用场景：
- 产品需求表格里改一行「状态」→ 自动生成「技术方案」AI 字段
- 招聘表格里改一行「面试反馈」→ 自动生成「推荐等级」AI 字段

Feishu 开发者平台配置：
  Bitable → 字段 → AI 字段 → 选择「Webhook (自定义)」→ 填我们的 API 地址
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("feishu_advanced.bitable_ai_node_v4")


def handle_bitable_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """飞书多维表格 AI Agent 节点的 webhook 入口。

    期望 payload schema:
    {
      "app_token": "...",
      "table_id": "...",
      "record_id": "...",
      "trigger_field": "状态",
      "trigger_value": "已提交",
      "context": {...其他字段...},
      "output_field": "技术方案",
      "tenant_id": "..."
    }
    """
    try:
        trigger_field = payload.get("trigger_field", "")
        trigger_value = payload.get("trigger_value", "")
        context = payload.get("context", {})
        output_field = payload.get("output_field", "ai_output")
        tenant_id = payload.get("tenant_id", "default")

        # Construct a task from the trigger
        intent = (
            f"多维表格触发：字段 [{trigger_field}] 的值变为 [{trigger_value}]。\n"
            f"上下文字段：{context}\n"
            f"请生成 [{output_field}] 字段的内容（简洁、可直接写回表格）。"
        )

        # Use OrchestratorWorker 'pilot' team for quality
        from agent.orchestrator_worker import default_orchestrator_worker
        ow = default_orchestrator_worker()
        result = ow.sync_run(intent, team="pilot", extra_context={
            "source": "bitable_ai_node",
            "trigger_field": trigger_field,
            "output_field": output_field,
            "tenant_id": tenant_id,
        })

        # Write back to Bitable
        app_token = payload.get("app_token", "")
        table_id = payload.get("table_id", "")
        record_id = payload.get("record_id", "")
        written = False
        if app_token and table_id and record_id:
            try:
                from core.feishu_advanced.bitable_agent import write_ai_field
                write_ai_field(
                    app_token=app_token, table_id=table_id,
                    record_id=record_id, field=output_field,
                    value=result.final_synthesis[:2000],
                )
                written = True
            except Exception as e:
                logger.warning("write_ai_field failed: %s", e)

        return {
            "ok": True,
            "output": result.final_synthesis,
            "cost_cny": result.cost_cny,
            "workers": len(result.worker_results),
            "bitable_written": written,
        }
    except Exception as e:
        logger.exception("bitable webhook failed")
        return {"ok": False, "error": str(e)}
