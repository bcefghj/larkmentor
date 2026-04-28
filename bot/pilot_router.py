"""Pilot 主流程入口路由 (PRD §5 + §6 + §7).

设计目的：
- 保留现有 ``bot/event_handler.py`` 1169 行（v1 LarkMentor 路由）作为 fallback
- 新增独立的 ``handle_chat_message`` / ``handle_card_action`` 纯函数，供 main.py
  在新版本中作为「Agent-Pilot 主入口」使用，不破坏 v1
- 全程不直接 import lark-oapi（接收已解析好的消息字典 / 卡片事件字典），
  这样可以独立单元测试 + 评委环境无飞书 token 也能跑

主流程：
  IM 文本消息（or 群聊讨论）
    │
    ├─ 用户 @机器人 + 显式指令 → 直接命中（pilot:<intent>）
    │
    ├─ 用户开启专注模式 → @shield 路径（不在本 router 范围）
    │
    └─ 普通群聊 / 私聊
         │
         ▼
  IntentDetector 三闸门
    │
    ├─ NOT_INTENT → 不响应（避免打扰）
    ├─ COOLDOWN / IGNORED → 不响应
    ├─ NEEDS_CLARIFY → 弹 task_clarify_card
    └─ READY → 弹 task_suggested_card

  卡片按钮回调
    │
    ├─ confirm  → TaskService.fire(USER_CONFIRM)
    ├─ assign   → 弹 assign_picker_card
    ├─ ignore   → cooldown.mark_ignored
    ├─ add_ctx  → 弹 context_confirm_card
    └─ ...
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.agent_pilot.application import (
    ChatMessage,
    ContextBuildOptions,
    ContextService,
    IntentDetector,
    IntentVerdict,
    PlannerService,
    TaskService,
    default_context_service,
    default_task_service,
)
from core.agent_pilot.domain import (
    SourceMessage,
    TaskEvent,
    TaskState,
)
from . import cards_pilot

logger = logging.getLogger("bot.pilot_router")


# Card sender: (open_id_or_chat_id, card_dict, *, scope) -> message_id
CardSender = Callable[..., str]


# ── 处理结果 ────────────────────────────────────────────────────────────────


@dataclass
class RouterResult:
    """每次处理消息/按钮后的统一结果（便于上层 logging + e2e 测试）."""

    handled: bool = False
    verdict: str = ""           # "ready" / "clarify" / "not_intent" / "cooldown" / ...
    task_id: str = ""
    card: Optional[Dict[str, Any]] = None
    next_action: str = ""        # 下一步建议（debug 用）
    error: str = ""


# ── 新主入口：消息 ──────────────────────────────────────────────────────────


class PilotRouter:
    """单例风格的 Pilot 主路由 facade."""

    def __init__(
        self,
        *,
        task_service: Optional[TaskService] = None,
        intent_detector: Optional[IntentDetector] = None,
        context_service: Optional[ContextService] = None,
        planner_service: Optional[PlannerService] = None,
        card_sender: Optional[CardSender] = None,
    ) -> None:
        self.task_service = task_service or default_task_service()
        self.intent_detector = intent_detector or IntentDetector()
        self.context_service = context_service or default_context_service()
        self.planner_service = planner_service or PlannerService(planner_factory=False)
        self.card_sender = card_sender or _default_card_sender
        # 保留群聊最近 N 条消息缓存（per chat_id）
        self._recent: Dict[str, List[ChatMessage]] = {}
        self._recent_max = 30

    # ── 消息入口 ──────────────────────────────────────────────────────────
    def handle_chat_message(self, *,
                            sender_open_id: str,
                            text: str,
                            chat_id: str = "",
                            msg_id: str = "",
                            workspace_id: str = "",
                            department_id: str = "",
                            tenant_id: str = "default",
                            in_focus_mode: bool = False,
                            ts: Optional[int] = None) -> RouterResult:
        """处理一条 IM 消息（已解析为纯参数）.

        - ``in_focus_mode=True`` 时，让 @shield v1 路径处理（本 router 跳过）
        - 否则走 IntentDetector 三闸门
        """
        if in_focus_mode:
            return RouterResult(handled=False, verdict="focus_mode_bypass",
                                  next_action="defer_to_shield_path")

        msg = ChatMessage(
            sender_open_id=sender_open_id, text=text or "",
            chat_id=chat_id or sender_open_id,
            msg_id=msg_id, ts=ts or int(time.time()),
        )
        # update recent buffer
        buf = self._recent.setdefault(msg.chat_id, [])
        buf.append(msg)
        if len(buf) > self._recent_max:
            del buf[: len(buf) - self._recent_max]

        # 显式 /pilot 指令直通（绕过三闸门）
        if text.lstrip().lower().startswith(("/pilot", "@pilot")):
            return self._handle_explicit_pilot(msg, workspace_id, department_id, tenant_id)

        # 三闸门
        candidate = self.intent_detector.detect(buf)
        if candidate.verdict == IntentVerdict.NOT_INTENT:
            return RouterResult(handled=True, verdict="not_intent",
                                 next_action="silent")
        if candidate.verdict in (IntentVerdict.COOLDOWN, IntentVerdict.IGNORED):
            return RouterResult(handled=True, verdict=candidate.verdict.value,
                                 next_action="silent")

        # READY / NEEDS_CLARIFY 都创建 Task
        task = self.task_service.create_task(
            intent=msg.text,
            owner_open_id=candidate.suggested_owner,
            source_chat_id=msg.chat_id,
            source_msg_id=msg.msg_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            department_id=department_id,
            title=candidate.suggested_title or msg.text[:40],
        )

        # 标 cooldown 防重复
        self.intent_detector.cooldown.mark_fired(msg.chat_id, candidate.theme_key)

        # 渲染卡片
        if candidate.verdict == IntentVerdict.NEEDS_CLARIFY:
            card = cards_pilot.task_clarify_card(
                task_id=task.task_id,
                detected_goal=candidate.llm_judgement.goal if candidate.llm_judgement else "",
                questions=candidate.clarify_questions,
            )
            verdict = "clarify"
        else:
            # READY
            ctx_state = {
                "used": len(buf),
                "missing": candidate.llm_judgement.resources if candidate.llm_judgement else [],
                "suggested": [],
            }
            plan_outline = self._heuristic_outline(msg.text)
            card = cards_pilot.task_suggested_card(
                task_id=task.task_id,
                title=task.title,
                intent=task.intent,
                source_chat=msg.chat_id,
                owner_open_id=task.owner_lock.owner_open_id,
                owner_display=task.owner_lock.owner_open_id[-6:],
                plan_outline=plan_outline,
                context_state=ctx_state,
            )
            verdict = "ready"

        try:
            self.card_sender(msg.chat_id, card, scope="chat")
        except Exception as e:
            logger.warning("card send failed: %s", e)

        return RouterResult(handled=True, verdict=verdict,
                            task_id=task.task_id, card=card,
                            next_action="awaiting_owner_action")

    # ── 按钮回调入口 ──────────────────────────────────────────────────────
    def handle_card_action(self, *,
                           actor_open_id: str,
                           action: str,
                           value: Dict[str, Any]) -> RouterResult:
        task_id = value.get("task_id", "")
        if not action:
            return RouterResult(handled=False, error="empty_action")

        # 路由各按钮
        if action == "pilot.task.confirm":
            return self._action_confirm(task_id, actor_open_id,
                                         skip_clarify=bool(value.get("skip_clarify")))
        if action == "pilot.task.ignore":
            return self._action_ignore(task_id, actor_open_id)
        if action == "pilot.task.add_context":
            return self._action_add_context(task_id, actor_open_id)
        if action == "pilot.task.assign":
            return self._action_open_assign(task_id, actor_open_id)
        if action == "pilot.task.assign_to":
            return self._action_assign_to(task_id, actor_open_id, value.get("to_open_id", ""))
        if action == "pilot.task.claim_self":
            return self._action_claim_self(task_id, actor_open_id)
        if action == "pilot.task.assign_cancel":
            return RouterResult(handled=True, verdict="cancel", task_id=task_id)
        if action == "pilot.ctx.confirm":
            return self._action_confirm_context(task_id, actor_open_id)
        if action == "pilot.ctx.add_more":
            return self._action_add_context(task_id, actor_open_id)
        if action == "pilot.task.pause":
            return self._action_pause(task_id, actor_open_id)
        if action == "pilot.task.archive":
            return self._action_deliver(task_id, actor_open_id)
        if action == "pilot.task.request_ppt":
            return self._action_request_ppt(task_id, actor_open_id)
        if action == "pilot.task.clarify_inline":
            return RouterResult(handled=True, verdict="clarify_inline",
                                 task_id=task_id, next_action="user_will_reply_inline")

        return RouterResult(handled=False, error=f"unknown_action: {action}")

    # ── private actions ──────────────────────────────────────────────────
    def _handle_explicit_pilot(self, msg: ChatMessage, workspace_id: str,
                                 department_id: str, tenant_id: str) -> RouterResult:
        """显式 /pilot 指令：直接创建 Task READY 状态."""
        intent = msg.text.split(maxsplit=1)
        body = intent[1] if len(intent) > 1 else ""
        if not body.strip():
            return RouterResult(handled=True, verdict="empty_explicit",
                                 next_action="ask_for_intent")
        task = self.task_service.create_task(
            intent=body, owner_open_id=msg.sender_open_id,
            source_chat_id=msg.chat_id, source_msg_id=msg.msg_id,
            tenant_id=tenant_id, workspace_id=workspace_id,
            department_id=department_id,
            title=body[:40],
        )
        plan_outline = self._heuristic_outline(body)
        card = cards_pilot.task_suggested_card(
            task_id=task.task_id, title=task.title, intent=body,
            source_chat=msg.chat_id,
            owner_open_id=msg.sender_open_id,
            owner_display=msg.sender_open_id[-6:],
            plan_outline=plan_outline,
            context_state={"used": 1, "missing": [], "suggested": []},
        )
        try:
            self.card_sender(msg.chat_id, card, scope="chat")
        except Exception:
            pass
        return RouterResult(handled=True, verdict="explicit_ready",
                             task_id=task.task_id, card=card)

    def _action_confirm(self, task_id: str, actor: str,
                         skip_clarify: bool = False) -> RouterResult:
        try:
            task = self.task_service.fire(task_id, TaskEvent.USER_CONFIRM,
                                            actor_open_id=actor)
        except Exception as e:
            return RouterResult(handled=False, task_id=task_id, error=str(e))

        # 触发上下文构建（Phase 1: skip_context_pending if has min context）
        cp_summary = self._build_initial_context(task)
        card = cards_pilot.context_confirm_card(task_id=task_id, summary=cp_summary)
        try:
            self.card_sender(actor, card, scope="user")
        except Exception:
            pass
        return RouterResult(handled=True, verdict="confirmed",
                             task_id=task_id, card=card,
                             next_action="awaiting_context_confirm")

    def _action_confirm_context(self, task_id: str, actor: str) -> RouterResult:
        try:
            task = self.task_service.fire(task_id, TaskEvent.USER_CONFIRM_CONTEXT,
                                           actor_open_id=actor)
            # 立即调 planner 生成 plan
            self.planner_service.plan_for_task(task)
        except Exception as e:
            return RouterResult(handled=False, task_id=task_id, error=str(e))

        # 进度卡占位（cardkit.v1 后续 patch）
        card = cards_pilot.task_progress_card(
            task_id=task_id,
            state=task.state.value,
            progress=0.1,
            current_step="正在规划",
            streaming_content="@pilot 拆解任务中...",
        )
        try:
            self.card_sender(actor, card, scope="user")
        except Exception:
            pass
        return RouterResult(handled=True, verdict="ctx_confirmed",
                             task_id=task_id, card=card,
                             next_action="orchestrator_can_start")

    def _action_ignore(self, task_id: str, actor: str) -> RouterResult:
        try:
            task = self.task_service.fire(task_id, TaskEvent.USER_IGNORE,
                                           actor_open_id=actor,
                                           enforce_owner_lock=False)
            self.intent_detector.cooldown.mark_ignored(
                task.source_chat_id,
                task.intent[:24],
            )
        except Exception as e:
            return RouterResult(handled=False, task_id=task_id, error=str(e))
        return RouterResult(handled=True, verdict="ignored", task_id=task_id)

    def _action_add_context(self, task_id: str, actor: str) -> RouterResult:
        task = self.task_service.get(task_id)
        if task is None:
            return RouterResult(handled=False, error="task_not_found")
        # 从 PLANNING/ASSIGNED 撤回到 CONTEXT_PENDING
        if task.state == TaskState.SUGGESTED:
            try:
                self.task_service.fire(task_id, TaskEvent.USER_CONFIRM, actor_open_id=actor)
            except Exception:
                pass
        if task.state == TaskState.ASSIGNED:
            try:
                self.task_service.fire(task_id, TaskEvent.USER_ADD_CONTEXT,
                                        actor_open_id=actor)
            except Exception:
                pass
        cp_summary = self._build_initial_context(task)
        card = cards_pilot.context_confirm_card(task_id=task_id, summary=cp_summary)
        try:
            self.card_sender(actor, card, scope="user")
        except Exception:
            pass
        return RouterResult(handled=True, verdict="ctx_pending",
                             task_id=task_id, card=card)

    def _action_open_assign(self, task_id: str, actor: str) -> RouterResult:
        # 在真实环境，candidates 来自 IM API。这里给空列表 + 「我来执行」按钮。
        card = cards_pilot.assign_picker_card(
            task_id=task_id, candidates=[],
            current_owner_open_id=actor,
        )
        try:
            self.card_sender(actor, card, scope="user")
        except Exception:
            pass
        return RouterResult(handled=True, verdict="assign_picker",
                             task_id=task_id, card=card)

    def _action_assign_to(self, task_id: str, actor: str, to_open_id: str) -> RouterResult:
        if not to_open_id:
            return RouterResult(handled=False, error="missing_to_open_id")
        try:
            self.task_service.assign(task_id, to_open_id=to_open_id, by_open_id=actor)
        except Exception as e:
            return RouterResult(handled=False, task_id=task_id, error=str(e))
        return RouterResult(handled=True, verdict="assigned", task_id=task_id)

    def _action_claim_self(self, task_id: str, actor: str) -> RouterResult:
        try:
            self.task_service.claim(task_id, by_open_id=actor)
        except Exception as e:
            return RouterResult(handled=False, task_id=task_id, error=str(e))
        return RouterResult(handled=True, verdict="claimed", task_id=task_id)

    def _action_pause(self, task_id: str, actor: str) -> RouterResult:
        try:
            self.task_service.fire(task_id, TaskEvent.USER_PAUSE,
                                    actor_open_id=actor,
                                    enforce_owner_lock=False)
        except Exception as e:
            return RouterResult(handled=False, task_id=task_id, error=str(e))
        return RouterResult(handled=True, verdict="paused", task_id=task_id)

    def _action_deliver(self, task_id: str, actor: str) -> RouterResult:
        try:
            self.task_service.fire(task_id, TaskEvent.USER_DELIVER,
                                    actor_open_id=actor)
        except Exception as e:
            return RouterResult(handled=False, task_id=task_id, error=str(e))
        return RouterResult(handled=True, verdict="delivered", task_id=task_id)

    def _action_request_ppt(self, task_id: str, actor: str) -> RouterResult:
        try:
            self.task_service.fire(task_id, TaskEvent.USER_REQUEST_PPT,
                                    actor_open_id=actor)
        except Exception as e:
            return RouterResult(handled=False, task_id=task_id, error=str(e))
        return RouterResult(handled=True, verdict="ppt_requested", task_id=task_id)

    # ── helpers ──────────────────────────────────────────────────────────
    def _build_initial_context(self, task) -> Dict[str, Any]:
        recent = self._recent.get(task.source_chat_id, [])
        im_msgs = [SourceMessage(sender_open_id=m.sender_open_id,
                                  text=m.text, chat_id=m.chat_id,
                                  msg_id=m.msg_id, ts=m.ts)
                    for m in recent[-12:]]
        cp = self.context_service.build(
            ContextBuildOptions(
                task_id=task.task_id, task_goal=task.intent,
                owner_open_id=task.owner_lock.owner_open_id,
                output_primary="ppt" if any(k in task.intent for k in ("PPT", "ppt", "汇报")) else "doc",
                output_audience="leader" if "老板" in task.intent else "",
                tenant_id=task.tenant_id,
                workspace_id=task.workspace_id,
                department_id=task.department_id,
                chat_id=task.source_chat_id,
                user_id=task.owner_lock.owner_open_id,
            ),
            im_messages=im_msgs,
        )
        task.attach_context(cp, confirmed=False)
        return self.context_service.render_confirm_summary(cp)

    @staticmethod
    def _heuristic_outline(intent: str) -> List[str]:
        out: List[str] = []
        if any(k in intent for k in ("PPT", "ppt", "演示", "汇报")):
            out += ["拉取上下文", "生成大纲", "生成 PPT", "演讲稿", "归档分享"]
        elif any(k in intent for k in ("画布", "白板", "架构图", "流程图")):
            out += ["拉取上下文", "创建画布", "添加形状", "归档分享"]
        else:
            out += ["拉取上下文", "生成文档大纲", "写入正文", "归档分享"]
        return out


# ── 默认 card_sender ───────────────────────────────────────────────────────


def _default_card_sender(target: str, card: Dict[str, Any], *, scope: str = "user") -> str:
    """无飞书 token 时的占位 sender（仅用于本地/测试）.

    在生产中由 ``main.py`` 注入真实的 ``bot.message_sender.send_card``."""
    logger.info("card-sender (stub) target=%s scope=%s body_keys=%s",
                target, scope, list(card.keys()))
    return f"stub-msg-{int(time.time() * 1000)}"


_default_router: Optional[PilotRouter] = None


def default_pilot_router() -> PilotRouter:
    global _default_router
    if _default_router is None:
        _default_router = PilotRouter()
    return _default_router


__all__ = ["PilotRouter", "RouterResult", "default_pilot_router"]
