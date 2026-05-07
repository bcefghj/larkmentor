"""飞书消息 + 卡片回调统一路由（V1.5）.

V1 → V1.5 关键演化:
  - IntentRouter 升级到 5 闸门，新增 CHAT verdict（绝不沉默）→ 在此分发为 text_reply。
  - COMMAND verdict 在 router 层处理，避免 bot.py 重复字符串匹配。
  - 卡片 actions 扩到 PRD §6/§7 全集（task / ctx / clarify）。
  - plan_launcher 签名增加 `needs_web_search` 透传，由 Planner 决定是否插 web.search 第 0 步。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pilot.capability.workforce.clarifier import Clarifier
from pilot.runtime.intent_router import (
    ChatMessage,
    IntentRouter,
    IntentVerdict,
)

logger = logging.getLogger("pilot.surface.feishu.router")


@dataclass
class RouterResult:
    handled: bool = False
    verdict: str = ""
    task_id: str = ""
    card: dict[str, Any] | None = None
    next_action: str = ""
    text_reply: str = ""
    error: str = ""


PlanLauncher = Callable[..., Awaitable[dict[str, Any]]]


class FeishuRouter:
    """5 闸门 + 卡片 action 单一路由."""

    def __init__(
        self,
        *,
        intent_router: IntentRouter | None = None,
        clarifier: Clarifier | None = None,
        plan_launcher: PlanLauncher | None = None,
    ) -> None:
        self.intent_router = intent_router or IntentRouter()
        self.clarifier = clarifier or Clarifier()
        self.plan_launcher = plan_launcher
        self._recent: dict[str, list[ChatMessage]] = {}
        self._max_recent = 30

    async def handle_message(
        self,
        *,
        sender_open_id: str,
        text: str,
        chat_id: str = "",
        msg_id: str = "",
        is_explicit: bool = False,
        is_p2p: bool = True,
    ) -> RouterResult:
        text = (text or "").strip()
        if not text:
            return RouterResult(handled=False, verdict="empty")

        chat_id = chat_id or sender_open_id

        msg = ChatMessage(
            sender_open_id=sender_open_id,
            text=text,
            chat_id=chat_id,
            msg_id=msg_id,
            ts=int(time.time()),
        )
        buf = self._recent.setdefault(chat_id, [])
        buf.append(msg)
        if len(buf) > self._max_recent:
            del buf[: len(buf) - self._max_recent]

        # is_explicit 调用方可强制走启动路径（用于卡片回调里组装的"启动意图"）
        if is_explicit:
            return await self._launch(
                intent=_strip_prefix(text),
                chat_id=chat_id,
                sender_open_id=sender_open_id,
                needs_web_search=False,
            )

        result = await self.intent_router.detect(buf, is_p2p=is_p2p)

        if result.verdict == IntentVerdict.NOT_INTENT:
            return RouterResult(handled=False, verdict="not_intent")

        if result.verdict in (IntentVerdict.COOLDOWN, IntentVerdict.IGNORED):
            return RouterResult(handled=True, verdict=result.verdict.value, next_action="silent")

        if result.verdict == IntentVerdict.COMMAND:
            return await self._handle_command(result.command_kind)

        if result.verdict == IntentVerdict.CHAT:
            from pilot.surface.feishu.cards import chat_reply_card
            friendly = result.chat_reply or "你好！有什么可以帮你的吗？"
            return RouterResult(
                handled=True,
                verdict="chat",
                card=chat_reply_card(reply=friendly),
            )

        if result.verdict == IntentVerdict.NEEDS_CLARIFY:
            req = self.clarifier.build_request(intent=text, questions=result.clarify_questions)
            return RouterResult(
                handled=True,
                verdict="clarify",
                card=req.to_card(),
                next_action="awaiting_user_clarify_answer",
            )

        # READY
        intent = _strip_prefix(text) if result.rule_hits and "explicit_pilot" in result.rule_hits else text
        return await self._launch(
            intent=intent,
            chat_id=chat_id,
            sender_open_id=sender_open_id,
            needs_web_search=result.needs_web_search,
        )

    async def handle_card_action(
        self,
        *,
        actor_open_id: str,
        action: str,
        value: dict[str, Any],
    ) -> RouterResult:
        if not action:
            return RouterResult(handled=False, error="empty_action")

        # 澄清卡按钮（V1 修复保留）
        if action == "pilot.clarify.choose":
            choice = value.get("choice", "doc")
            intent = value.get("intent", "")
            expanded = self.clarifier.expand_choice(intent=intent, choice=choice)
            return await self._launch(
                intent=expanded,
                chat_id=actor_open_id,
                sender_open_id=actor_open_id,
                needs_web_search=False,
            )

        if action == "pilot.clarify.skip":
            intent = value.get("intent", "") or "Agent-Pilot 任务"
            return await self._launch(
                intent=intent,
                chat_id=actor_open_id,
                sender_open_id=actor_open_id,
                needs_web_search=False,
            )

        # 任务卡片按钮（PRD §F-04 / §6）
        if action == "pilot.task.confirm":
            return RouterResult(
                handled=True,
                verdict="confirmed",
                task_id=value.get("task_id", ""),
                next_action="orchestrator_running",
                text_reply="✅ 已确认，开始执行",
            )
        if action == "pilot.task.ignore":
            return RouterResult(
                handled=True,
                verdict="ignored",
                task_id=value.get("task_id", ""),
                text_reply="🙅 已忽略本次建议",
            )
        if action == "pilot.task.assign":
            return RouterResult(
                handled=True,
                verdict="assign_pending",
                task_id=value.get("task_id", ""),
                text_reply="👤 请 @ 一位群成员，回复 `指派 @某人` 完成转交",
            )
        if action == "pilot.task.claim":
            return RouterResult(
                handled=True,
                verdict="claimed",
                task_id=value.get("task_id", ""),
                text_reply=f"✋ 已由 {actor_open_id[-6:]} 接管",
            )
        if action == "pilot.task.archive":
            return RouterResult(
                handled=True,
                verdict="archived",
                task_id=value.get("task_id", ""),
                text_reply="📁 已归档",
            )
        if action == "pilot.task.pause":
            return RouterResult(
                handled=True,
                verdict="paused",
                task_id=value.get("task_id", ""),
                text_reply="⏸ 已暂停，发送 `继续` 恢复",
            )

        # 上下文确认卡片按钮（PRD §7.2）
        if action in ("pilot.ctx.add", "pilot.task.add_context"):
            return RouterResult(
                handled=True,
                verdict="ctx_add",
                task_id=value.get("task_id", ""),
                text_reply="📎 请直接发送补充资料的链接或文件，我会自动加入上下文包",
            )
        if action == "pilot.ctx.confirm":
            return RouterResult(
                handled=True,
                verdict="ctx_confirmed",
                task_id=value.get("task_id", ""),
                text_reply="✅ 上下文已确认，正在生成产物...",
            )
        if action == "pilot.ctx.adjust":
            return RouterResult(
                handled=True,
                verdict="ctx_adjust",
                task_id=value.get("task_id", ""),
                text_reply="📝 请直接发新的目标描述，我会重置规划并重新启动",
            )

        if action == "pilot.help":
            from pilot.surface.feishu.cards import help_card
            return RouterResult(handled=True, verdict="help", card=help_card())

        return RouterResult(handled=False, error=f"unknown_action: {action}")

    async def _handle_command(self, kind: str) -> RouterResult:
        if kind == "help":
            from pilot.surface.feishu.cards import help_card
            return RouterResult(handled=True, verdict="help_command", card=help_card())
        if kind == "status":
            return RouterResult(
                handled=True,
                verdict="status",
                text_reply="📊 当前没有正在执行的任务。发送任务描述即可启动新计划。",
            )
        if kind == "claim":
            return RouterResult(handled=True, verdict="claim", text_reply="✋ 已记录认领，请确认任务卡里的 task_id")
        if kind == "pause":
            return RouterResult(handled=True, verdict="pause", text_reply="⏸ 已暂停（需带 task_id 才能精确定位）")
        if kind == "resume":
            return RouterResult(handled=True, verdict="resume", text_reply="▶️ 收到，请告诉我要恢复的 task_id")
        if kind == "ignore":
            return RouterResult(handled=True, verdict="ignore", text_reply="🙅 已忽略本次")
        return RouterResult(handled=True, verdict=f"command:{kind}")

    async def _launch(
        self,
        *,
        intent: str,
        chat_id: str,
        sender_open_id: str,
        needs_web_search: bool = False,
    ) -> RouterResult:
        if self.plan_launcher is None:
            return RouterResult(
                handled=True,
                verdict="ready",
                text_reply=f"🛫 收到意图：{intent[:60]}\n（plan_launcher 未注入）",
            )

        try:
            res = await self.plan_launcher(
                intent=intent,
                chat_id=chat_id,
                sender_open_id=sender_open_id,
                needs_web_search=needs_web_search,
            )
        except TypeError:
            # 兼容旧签名（无 needs_web_search）
            res = await self.plan_launcher(
                intent=intent,
                chat_id=chat_id,
                sender_open_id=sender_open_id,
            )
        except Exception as e:
            logger.exception("launch failed: %s", e)
            return RouterResult(handled=True, verdict="error", text_reply=f"❌ 启动失败: {e}", error=str(e))

        return RouterResult(
            handled=True,
            verdict="ready",
            task_id=res.get("plan_id", ""),
            text_reply=res.get("ack_text", f"🛫 已启动 Agent-Pilot · {intent[:30]}"),
            card=res.get("card"),
        )


def _strip_prefix(text: str) -> str:
    text = (text or "").strip()
    for p in ("/pilot", "@pilot", "/Pilot", "@Pilot"):
        if text.lower().startswith(p.lower()):
            return text[len(p):].strip(":：、 ").strip()
    return text
