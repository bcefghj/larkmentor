"""飞书 lark-oapi WebSocket 长连接 Bot 入口（V1.5）.

启动:
    python -m pilot bot

V1 → V1.5 关键演化:
  - 注入 LLM judge（MiniMax）到 IntentRouter 闸门 4。
  - 内存版 idempotency：60s 内同 (sender, md5(text)) 去重，避免重复创建任务。
  - 删除所有硬编码 IP；URL 走 DASHBOARD_PUBLIC_BASE，留空则用相对路径。
  - artifacts 收集去重 + 过滤空 URL（修 V1 卡片里出现 [](　) 的空链接 bug）。
  - plan_launcher 透传 needs_web_search → Planner 可决定是否插 web.search 第 0 步。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("pilot.surface.feishu.bot")


JUDGE_PROMPT = (
    "你是飞书办公助手 Agent-Pilot 的意图分类器。\n"
    "分类规则：\n"
    "- ready: 用户在表达明确的任务意图（要做文档/PPT/画布/三件套等），且信息够（有目标 + 有形态）\n"
    "- chat: 闲聊、打招呼、感谢、表情、问与办公任务无关的事\n"
    "- clarify: 是任务但信息不够（缺目标/缺受众/缺形态/缺时间）\n"
    "- not_intent: 空消息或纯符号\n\n"
    "只输出 JSON，不要任何额外文字：\n"
    "{\n"
    '  "verdict": "ready|chat|clarify|not_intent",\n'
    '  "task_type": "doc|ppt|canvas|trio|none",\n'
    '  "summary": "任务一句话归纳，<=20 字",\n'
    '  "missing": ["audience","form","goal","time"],\n'
    '  "friendly_reply": "如果是 chat，给一句友好回复，<=40 字。否则空字符串",\n'
    '  "needs_web_search": false\n'
    "}\n"
)


def _public_dashboard_url(plan_id: str) -> str:
    """Dashboard 链接生成器；DASHBOARD_PUBLIC_BASE 留空则只给相对路径."""
    base = (os.getenv("DASHBOARD_PUBLIC_BASE") or "").rstrip("/")
    return f"{base}/dashboard?plan_id={plan_id}" if base else f"/dashboard?plan_id={plan_id}"


def _absolute_artifact_url(rel_or_abs: str) -> str:
    """如果是相对 /artifacts/... 路径且配了 base，就拼成绝对 URL；否则原样返回."""
    if not rel_or_abs:
        return ""
    if rel_or_abs.startswith(("http://", "https://")):
        return rel_or_abs
    base = (os.getenv("DASHBOARD_PUBLIC_BASE") or "").rstrip("/")
    if rel_or_abs.startswith("/") and base:
        return f"{base}{rel_or_abs}"
    return rel_or_abs


def run() -> None:
    if not os.getenv("FEISHU_APP_ID") or os.getenv("FEISHU_APP_ID") == "cli_your_app_id_here":
        logger.error("未配置 FEISHU_APP_ID，无法启动 bot")
        return

    try:
        import lark_oapi as lark
    except ImportError:
        logger.error("lark-oapi 未安装：pip install lark-oapi")
        return

    from pilot.capability.tools.registry import default_registry
    from pilot.llm.client import default_client
    from pilot.llm.safe_json import safe_json_parse
    from pilot.runtime.intent_router import ChatMessage, IntentRouter, LLMJudgement
    from pilot.runtime.orchestrator import Orchestrator
    from pilot.runtime.planner import plan_from_intent
    from pilot.surface.feishu.client import get_feishu_client
    from pilot.surface.feishu.router import FeishuRouter

    feishu = get_feishu_client()

    # ── LLM Judge（闸门 4）+ 内存 LRU 缓存 ──
    _judge_cache: dict[str, tuple[float, LLMJudgement]] = {}
    _judge_cache_ttl = 600.0

    async def _llm_judge(text: str, history: list[ChatMessage]) -> LLMJudgement:
        cache_key = hashlib.md5(text.encode("utf-8")).hexdigest()[:16]
        now = time.time()
        cached = _judge_cache.get(cache_key)
        if cached and (now - cached[0] < _judge_cache_ttl):
            return cached[1]

        history_str = "\n".join(f"- {m.text[:120]}" for m in history[-5:] if m.text) or f"- {text[:120]}"
        user_prompt = f"用户消息历史：\n{history_str}\n\n请输出 JSON 判断结果。"

        try:
            resp = await asyncio.wait_for(
                default_client().chat(
                    system=JUDGE_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                    temperature=0.0,
                    max_tokens=256,
                    response_format={"type": "json_object"},
                ),
                timeout=8.0,
            )
        except asyncio.TimeoutError:
            logger.warning("LLM judge timeout (8s)")
            return LLMJudgement(verdict="not_intent")
        except Exception as e:
            logger.warning("LLM judge failed: %s", e)
            return LLMJudgement(verdict="not_intent")

        text_resp = resp.get("text", "") or ""
        if not text_resp:
            for blk in resp.get("content", []) or []:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    text_resp = blk.get("text", "")
                    break

        obj = safe_json_parse(text_resp) or {}
        j = LLMJudgement(
            verdict=obj.get("verdict", "not_intent"),
            is_task=obj.get("verdict") in ("ready", "clarify"),
            task_type=obj.get("task_type", "none"),
            summary=str(obj.get("summary", ""))[:30],
            missing=obj.get("missing") or [],
            friendly_reply=str(obj.get("friendly_reply", ""))[:60],
            needs_web_search=bool(obj.get("needs_web_search", False)),
        )
        _judge_cache[cache_key] = (now, j)
        return j

    # ── idempotency：60s 内同 (sender, text-hash) 去重 ──
    _idempotency: dict[str, float] = {}

    def _is_dup(sender: str, text: str) -> bool:
        key = f"{sender}::{hashlib.md5(text.encode('utf-8')).hexdigest()[:12]}"
        now = time.time()
        for k in [k for k, t in _idempotency.items() if now - t > 120]:
            _idempotency.pop(k, None)
        if key in _idempotency and now - _idempotency[key] < 60:
            return True
        _idempotency[key] = now
        return False

    async def _plan_launcher(
        *,
        intent: str,
        chat_id: str,
        sender_open_id: str,
        needs_web_search: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        plan = plan_from_intent(
            intent,
            user_open_id=sender_open_id,
            meta={"needs_web_search": needs_web_search},
        )
        ack = (
            f"🛫 **Agent-Pilot V1.5 已启动**\n"
            f"Plan: `{plan.plan_id}`\n"
            f"意图：{intent[:80]}\n\n"
            f"📋 计划（共 {len(plan.steps)} 步）：\n"
            + "\n".join(
                f"  {i + 1}. [{s.tool}] {s.description}"
                for i, s in enumerate(plan.steps[:6])
            )
        )
        dash = _public_dashboard_url(plan.plan_id)
        if dash:
            ack += f"\n\n实时进度：{dash}"

        def _bg() -> None:
            asyncio.run(_run_plan_in_bg(plan, chat_id))

        threading.Thread(target=_bg, daemon=True).start()
        return {"plan_id": plan.plan_id, "ack_text": ack}

    async def _run_plan_in_bg(plan, chat_id: str) -> None:
        from pilot.context.event_log import EventLog
        from pilot.surface.feishu.cards import task_delivered_card

        event_log = EventLog(session_id=plan.plan_id)
        await event_log.append("plan_start", {
            "plan_id": plan.plan_id,
            "intent": plan.intent,
            "steps": [{"step_id": s.step_id, "tool": s.tool, "description": s.description} for s in plan.steps],
        })

        async def _on_event(ev) -> None:
            await event_log.append(ev.kind, {"step_id": ev.step_id, "tool": ev.tool, **ev.payload})

        try:
            summary = await Orchestrator(default_registry(), on_event=_on_event).run(plan)

            artifacts = _collect_artifacts(summary)

            await event_log.append("plan_done", {
                "plan_id": plan.plan_id,
                "completed": summary.get("completed", []),
                "failed": summary.get("failed", []),
                "artifacts": artifacts,
            })

            card = task_delivered_card(
                task_id=plan.plan_id,
                title=plan.intent[:40],
                artifacts=artifacts,
            )
            await feishu.send_card(
                receive_id=chat_id,
                card=card,
                receive_id_type="chat_id" if chat_id.startswith("oc_") else "open_id",
            )
        except Exception as e:
            logger.exception("background plan failed: %s", e)
            await event_log.append("plan_error", {"error": str(e)[:500]})
            await feishu.send_text(
                receive_id=chat_id,
                text=f"❌ 任务失败：{e}",
                receive_id_type="chat_id" if chat_id.startswith("oc_") else "open_id",
            )

    intent_router = IntentRouter(llm_judge=_llm_judge)
    router = FeishuRouter(intent_router=intent_router, plan_launcher=_plan_launcher)

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

            content_raw = message.content or "{}"
            text = ""
            try:
                content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
                text = content.get("text", "") or ""
            except Exception:
                text = ""

            if not text and getattr(message, "message_type", "") == "audio":
                file_key = (json.loads(message.content) or {}).get("file_key", "")
                if file_key:
                    asyncio.run(_voice_transcribe(message_id, file_key, sender_open_id, message.chat_id, chat_type))
                    return

            if not text:
                return

            if _is_dup(sender_open_id, text):
                logger.info("duplicate msg ignored: sender=%s text=%s", sender_open_id[-6:], text[:40])
                return

            chat_id = message.chat_id if chat_type != "p2p" else sender_open_id
            is_p2p = chat_type == "p2p"

            res = asyncio.run(router.handle_message(
                sender_open_id=sender_open_id,
                text=text,
                chat_id=chat_id,
                msg_id=message_id,
                is_p2p=is_p2p,
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

    async def _voice_transcribe(message_id: str, file_key: str, sender: str, chat_id: str, chat_type: str) -> None:
        text = await feishu.transcribe_audio(message_id=message_id, file_key=file_key)
        if not text:
            await feishu.reply_text(message_id=message_id, text="🎤 没听清，请再发一次或直接发文字")
            return
        if _is_dup(sender, text):
            return
        target_chat = chat_id if chat_type != "p2p" else sender
        res = await router.handle_message(
            sender_open_id=sender,
            text=text,
            chat_id=target_chat,
            msg_id=message_id,
            is_p2p=(chat_type == "p2p"),
        )
        if res.text_reply:
            await feishu.reply_text(message_id=message_id, text=f"🎤 [识别] {text}\n\n{res.text_reply}")
        if res.card:
            await feishu.send_card(
                receive_id=target_chat,
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
    base = (os.getenv("DASHBOARD_PUBLIC_BASE") or "").rstrip("/") or "(未配置 DASHBOARD_PUBLIC_BASE)"
    logger.info("Agent-Pilot V1.5 bot 启动；公网入口 = %s", base)
    cli.start()


def _collect_artifacts(summary: dict[str, Any]) -> list[dict[str, str]]:
    """从 orchestrator summary.step_results 抽取产物，去重 + 过滤空 URL.

    输出格式：[{"kind":"doc|canvas|slide", "title":..., "url":...}, ...]
    """
    artifacts: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _sid, r in (summary.get("step_results") or {}).items():
        if not isinstance(r, dict):
            continue

        if r.get("doc_token"):
            url = (r.get("url") or "").strip()
            if not url and r.get("markdown_artifact"):
                url = str((r["markdown_artifact"] or {}).get("uri", "") or "")
            url = _absolute_artifact_url(url)
            ttl = str(r.get("title", "") or "飞书文档")
            key = ("doc", url)
            if url and key not in seen:
                seen.add(key)
                artifacts.append({"kind": "doc", "title": ttl, "url": url})

        if r.get("canvas_id"):
            cu = (r.get("tldraw_url") or r.get("url") or "").strip()
            cu = _absolute_artifact_url(cu)
            ttl = str(r.get("title", "") or "画布")
            key = ("canvas", cu)
            if cu and key not in seen:
                seen.add(key)
                artifacts.append({"kind": "canvas", "title": ttl, "url": cu})

        if r.get("slide_id"):
            pu = (r.get("pptx_url_absolute") or r.get("pptx_url") or r.get("url") or "").strip()
            pu = _absolute_artifact_url(pu)
            ttl = str(r.get("title", "") or "演示稿")
            key = ("slide", pu)
            if pu and key not in seen:
                seen.add(key)
                artifacts.append({"kind": "slide", "title": ttl, "url": pu})

    return artifacts
