#!/usr/bin/env python3
"""Agent-Pilot · 从 IM 对话到演示稿的一键智能闭环.

主入口：启动飞书长连接 + 卡片回调 + 定时任务 + 日历轮询 + Mentor 周日摘要
三线产品：@pilot 主驾驶 · @shield 消息守护 · @mentor 表达带教
"""

import logging
import os
import signal
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lark_oapi as lark

from bot.event_handler import on_card_action, on_message_receive, set_scheduler
from config import Config
from core.advanced_features import load as load_decisions
from core.analytics import send_all_daily_reports
from core.feishu_workspace_init import load_all as load_workspaces
from core.notification_channels import init_dispatcher
from core.sender_profile import decay_recent_counts
from core.sender_profile import load as load_sender_profiles
from core.structured_logging import configure_logging
from memory.user_state import _load_org_docs, load_all

configure_logging()
logger = logging.getLogger("agent-pilot")


def _validate_config():
    if not Config.FEISHU_APP_ID or Config.FEISHU_APP_ID == "your_app_id_here":
        logger.error("请在 .env 文件中配置 FEISHU_APP_ID")
        sys.exit(1)
    if not Config.FEISHU_APP_SECRET or Config.FEISHU_APP_SECRET == "your_app_secret_here":
        logger.error("请在 .env 文件中配置 FEISHU_APP_SECRET")
        sys.exit(1)
    logger.info("配置校验通过")


def _start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler()

        # Daily report at configured time
        scheduler.add_job(
            send_all_daily_reports,
            "cron",
            hour=Config.DAILY_REPORT_HOUR,
            minute=Config.DAILY_REPORT_MINUTE,
        )
        # Weekly report on Friday 17:00
        scheduler.add_job(
            send_all_daily_reports,
            "cron",
            day_of_week="fri",
            hour=17,
            minute=0,
        )
        # Calendar polling
        scheduler.add_job(
            _poll_calendar,
            "interval",
            minutes=Config.CALENDAR_POLL_MINUTES,
        )
        # Sender profile rolling-window decay (daily)
        scheduler.add_job(
            decay_recent_counts,
            "cron",
            hour=3,
            minute=0,
        )

        # ── v4 Mentor: weekly growth summary (Sunday 21:00) ──
        scheduler.add_job(
            _coach_weekly_growth_summary,
            "cron",
            day_of_week="sun",
            hour=21,
            minute=0,
        )

        scheduler.start()
        set_scheduler(scheduler)
        logger.info(
            "定时任务已启动: 日报 %02d:%02d | 周报 周五17:00 | 日历轮询 %d分钟",
            Config.DAILY_REPORT_HOUR,
            Config.DAILY_REPORT_MINUTE,
            Config.CALENDAR_POLL_MINUTES,
        )
        return scheduler
    except ImportError:
        logger.warning("apscheduler 未安装，跳过定时任务")
        return None


def _poll_calendar():
    """Check calendar events and auto-enter/exit focus mode."""
    try:
        from bot.message_sender import send_text
        from core.context_recall import capture_snapshot
        from memory.user_state import all_users
        from utils.feishu_api import get_current_calendar_events

        events = get_current_calendar_events()
        if not events:
            return

        focus_keywords = Config.FOCUS_KEYWORDS_IN_CALENDAR
        has_focus_event = any(any(kw.lower() in ev.lower() for kw in focus_keywords) for ev in events)

        if has_focus_event:
            for user in all_users():
                if not user.is_focusing():
                    user.start_focus(duration_min=0, context="日历检测到专注日程")
                    capture_snapshot(user)
                    send_text(
                        user.open_id,
                        "检测到日历中有专注/深度工作日程，已自动开启保护模式。\n\n发送 `结束专注` 可随时关闭。",
                    )
                    logger.info("Auto-focus for user %s via calendar", user.open_id)
    except Exception as e:
        logger.debug("Calendar poll error (non-critical): %s", e)


def _coach_weekly_growth_summary():
    """Sunday 21:00 cron · write a weekly growth summary for every active user."""
    try:
        from core.mentor.growth_doc import write_weekly_summary
        from memory.user_state import all_users

        for user in all_users():
            if not getattr(user, "rookie_mode", False):
                continue
            try:
                summary = write_weekly_summary(user.open_id)
                if summary:
                    logger.info(
                        "coach_weekly_summary user=%s len=%d",
                        user.open_id[-6:],
                        len(summary),
                    )
            except Exception as e:
                logger.debug("coach_weekly_summary user=%s err=%s", user.open_id[-6:], e)
    except Exception as e:
        logger.debug("coach_weekly_summary cron err=%s", e)


def _graceful_shutdown(signum, frame):
    logger.info("Agent-Pilot 收到终止信号 (%s)，正在优雅关闭...", signal.Signals(signum).name)
    sys.exit(0)


def main():
    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)

    dashboard_port = int(os.getenv("DASHBOARD_PORT", "8001") or "8001")
    sync_port = int(os.getenv("SYNC_HUB_PORT", "8002") or "8002")
    print(r"""
    ╔══════════════════════════════════════════════════════════╗
    ║  Agent-Pilot v12 · 三线产品 · 飞书 AI 校园挑战赛          ║
    ║  从 IM 对话到演示稿的一键智能闭环                          ║
    ║                                                          ║
    ║  [✓] @pilot   主驾驶 · IntentDetector + ContextPack +     ║
    ║              5 推理模式 + 多 Agent + 学习闭环             ║
    ║  [✓] @shield  消息守护 · 6 维分类 + Recovery Card 双线点  ║
    ║  [✓] @mentor  表达带教 · Write/Task/Review/Onboard 4 Skills ║
    ║                                                          ║
    ║  Bot       :  飞书 lark-oapi WebSocket 长连接             ║""")
    print(f"    ║  Dashboard :  http://0.0.0.0:{dashboard_port:<5}/tasks                  ║")
    print(f"    ║  Sync Hub  :  ws://0.0.0.0:{sync_port:<5}/sync                      ║")
    print(r"""    ║                                                          ║
    ║  在飞书发送  /pilot <意图>  启动主驾驶                     ║
    ║  或在群聊中自然提到任务，Agent 主动识别（PRD §5）          ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    _validate_config()

    # Register DI container defaults (lazy factories for all core services)
    from core.container import register_defaults
    register_defaults()

    # Load persisted state
    load_all()
    _load_org_docs()
    load_sender_profiles()
    load_decisions()
    load_workspaces()
    init_dispatcher()

    # ── v7 Pilot: subscribe learner to event bus (auto SKILL.md after 3 similar) ──
    try:
        from core.agent_pilot.application import default_pilot_learner

        default_pilot_learner().attach_to_bus()
        logger.info("PilotLearner attached to domain event bus")
    except Exception as e:
        logger.debug("PilotLearner attach failed (non-critical): %s", e)

    # ── v7 Pilot: bind 6-tier memory resolver to ContextService ──
    try:
        from core.agent_pilot.application import attach_memory_to_default_services

        attach_memory_to_default_services()
        logger.info("6-tier flow_memory_md resolver attached to ContextService")
    except Exception as e:
        logger.debug("memory bind failed (non-critical): %s", e)

    _start_scheduler()

    # Register BOTH message events AND card action callbacks
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message_receive)
        .register_p2_card_action_trigger(on_card_action)
        .build()
    )

    cli = lark.ws.Client(
        Config.FEISHU_APP_ID,
        Config.FEISHU_APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.DEBUG,
    )

    logger.info("正在连接飞书长连接服务...")
    logger.info("连接成功后，在飞书中搜索 Agent-Pilot 机器人开始使用")
    logger.info("按 Ctrl+C 停止")

    try:
        cli.start()
    except KeyboardInterrupt:
        logger.info("Agent-Pilot 已停止")


if __name__ == "__main__":
    main()
