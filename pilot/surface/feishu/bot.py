"""飞书 lark-oapi WebSocket 长连接 Bot 入口.

启动:
    python -m pilot bot

设计:
  - 用 lark-oapi 监听 IM 消息 + 卡片回调
  - 把消息打进 FeishuRouter（asyncio）
  - 把回调结果（text / card / 任务启动）回写飞书
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from typing import Any

logger = logging.getLogger("pilot.surface.feishu.bot")


def run() -> None:
    """阻塞启动飞书机器人."""
    if not os.getenv("FEISHU_APP_ID") or os.getenv("FEISHU_APP_ID") == "cli_your_app_id_here":
        logger.error("未配置 FEISHU_APP_ID，无法启动 bot")
        return

    try:
        import lark_oapi as lark
    except ImportError:
        logger.error("lark-oapi 未安装：pip install lark-oapi")
        return

    from pilot.surface.feishu.client import get_feishu_client
    from pilot.surface.feishu.router import FeishuRouter
    from pilot.runtime.intent_router import IntentRouter
    from pilot.runtime.planner import plan_from_intent
    from pilot.runtime.orchestrator import Orchestrator
    from pilot.capability.tools.registry import default_registry

    feishu = get_feishu_client()

    # 注入 plan_launcher
    async def _plan_launcher(*, intent: str, chat_id: str, sender_open_id: str) -> dict[str, Any]:
        plan = plan_from_intent(intent, user_open_id=sender_open_id)
        ack = (
            f"🛫 **Agent-Pilot V1 已启动**\n"
            f"Plan: `{plan.plan_id}`\n"
            f"意图：{intent[:80]}\n\n"
            f"📋 计划（共 {len(plan.steps)} 步）：\n"
            + "\n".join(f"  {i + 1}. [{s.tool}] {s.description}" for i, s in enumerate(plan.steps[:6]))
            + f"\n\n实时进度：http://118.178.242.26/dashboard?plan_id={plan.plan_id}"
        )

        # 启动后台执行
        def _bg():
            asyncio.run(_run_plan_in_bg(plan, chat_id))

        threading.Thread(target=_bg, daemon=True).start()

        return {"plan_id": plan.plan_id, "ack_text": ack}

    async def _run_plan_in_bg(plan, chat_id: str):
        from pilot.context.event_log import EventLog

        event_log = EventLog(session_id=plan.plan_id)
        event_log.append("plan_start", {
            "plan_id": plan.plan_id,
            "intent": plan.intent,
            "steps": [{"step_id": s.step_id, "tool": s.tool, "description": s.description} for s in plan.steps],
        })

        async def _on_event(ev):
            event_log.append(ev.kind, {"step_id": ev.step_id, "tool": ev.tool, **ev.payload})

        registry = default_registry()
        orch = Orchestrator(registry, on_event=_on_event)
        try:
            summary = await orch.run(plan)
            # 完成回写
            from pilot.surface.feishu.cards import task_delivered_card

            artifacts = []
            for sid, r in (summary.get("step_results") or {}).items():
                if not isinstance(r, dict):
                    continue
                if "doc_token" in r:
                    artifacts.append({"kind": "doc", "title": r.get("title", ""), "url": r.get("url", "")})
                if "canvas_id" in r:
                    artifacts.append({"kind": "canvas", "title": r.get("title", ""), "url": r.get("tldraw_url", "")})
                if "slide_id" in r and r.get("pptx_url"):
                    artifacts.append({"kind": "slide", "title": r.get("title", ""), "url": r["pptx_url"]})

            event_log.append("plan_done", {
                "plan_id": plan.plan_id,
                "completed": summary.get("completed", []),
                "failed": summary.get("failed", []),
                "artifacts": artifacts,
            })

            card = task_delivered_card(task_id=plan.plan_id, title=plan.intent[:40], artifacts=artifacts)
            await feishu.send_card(receive_id=chat_id, card=card,
                                   receive_id_type="chat_id" if chat_id.startswith("oc_") else "open_id")
        except Exception as e:
            logger.exception("background plan failed: %s", e)
            event_log.append("plan_error", {"error": str(e)[:500]})
            await feishu.send_text(receive_id=chat_id, text=f"❌ 任务失败：{e}",
                                   receive_id_type="chat_id" if chat_id.startswith("oc_") else "open_id")

    router = FeishuRouter(plan_launcher=_plan_launcher)

    # ── lark-oapi 事件分发 ──
    def _on_message(data) -> None:
        threading.Thread(target=_handle_message, args=(data,), daemon=True).start()

    def _handle_message(data) -> None:
        try:
            event = data.event
            message = event.message
            sender = event.sender
            chat_type = message.chat_type
            message_id = message.message_id
            sender_open_id = sender.sender_id.open_id if sender.sender_id else ""
            sender_type = sender.sender_type

            if sender_type != "user":
                return

            # 提取文本
            content_raw = message.content or "{}"
            text = ""
            try:
                content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
                text = content.get("text", "") or ""
            except Exception:
                text = ""

            # 语音转写
            if not text and getattr(message, "message_type", "") == "audio":
                file_key = (json.loads(message.content) or {}).get("file_key", "")
                if file_key:
                    asyncio.run(_voice_transcribe(message_id, file_key, sender_open_id, message.chat_id, chat_type))
                    return

            if not text:
                return

            chat_id = message.chat_id if chat_type != "p2p" else sender_open_id
            res = asyncio.run(router.handle_message(
                sender_open_id=sender_open_id,
                text=text,
                chat_id=chat_id,
                msg_id=message_id,
            ))
            if res.text_reply:
                asyncio.run(feishu.reply_text(message_id=message_id, text=res.text_reply))
            if res.card:
                asyncio.run(feishu.send_card(
                    receive_id=chat_id,
                    card=res.card,
                    receive_id_type="chat_id" if chat_type != "p2p" else "open_id",
                ))
        except Exception as e:
            logger.exception("on_message error: %s", e)

    async def _voice_transcribe(message_id: str, file_key: str, sender: str, chat_id: str, chat_type: str):
        text = await feishu.transcribe_audio(message_id=message_id, file_key=file_key)
        if not text:
            await feishu.reply_text(message_id=message_id, text="🎤 没听清，请再发一次或直接发文字")
            return
        res = await router.handle_message(
            sender_open_id=sender,
            text=text,
            chat_id=chat_id if chat_type != "p2p" else sender,
            msg_id=message_id,
        )
        if res.text_reply:
            await feishu.reply_text(message_id=message_id, text=f"🎤 [识别] {text}\n\n{res.text_reply}")
        if res.card:
            await feishu.send_card(
                receive_id=chat_id if chat_type != "p2p" else sender,
                card=res.card,
                receive_id_type="chat_id" if chat_type != "p2p" else "open_id",
            )

    def _on_card_action(data):
        try:
            action_value = data.event.action.value or {}
            action = action_value.get("action", "")
            open_id = data.event.operator.open_id
            res = asyncio.run(router.handle_card_action(
                actor_open_id=open_id,
                action=action,
                value=action_value,
            ))
            if res.text_reply:
                asyncio.run(feishu.send_text(receive_id=open_id, text=res.text_reply))
            if res.card:
                asyncio.run(feishu.send_card(receive_id=open_id, card=res.card))

            return type(data).response_class()({
                "toast": {"type": "info", "content": "处理中..." if res.handled else "未识别按钮"},
            })
        except Exception as e:
            logger.exception("card_action error: %s", e)
            return type(data).response_class()({"toast": {"type": "error", "content": "处理失败"}})

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_on_message)
        .register_p2_card_action_trigger(_on_card_action)
        .build()
    )

    # lark-oapi 不同版本 LogLevel 枚举不同，做兼容处理
    log_level = None
    for cand in ("WARNING", "WARN", "INFO", "ERROR"):
        if hasattr(lark.LogLevel, cand):
            log_level = getattr(lark.LogLevel, cand)
            break

    cli = lark.ws.Client(
        os.getenv("FEISHU_APP_ID", ""),
        os.getenv("FEISHU_APP_SECRET", ""),
        event_handler=handler,
        log_level=log_level,
    )
    logger.info("正在连接飞书长连接服务...")
    cli.start()
