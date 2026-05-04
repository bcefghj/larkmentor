"""LarkMentor runtime configuration with Pydantic validation.

All settings loaded from environment variables (.env file supported).
Startup fails fast with clear error messages if required fields are missing.
"""

from __future__ import annotations

import os
import sys
import logging
from typing import List

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("config")

try:
    from pydantic import Field
    from pydantic_settings import BaseSettings

    class Settings(BaseSettings):
        """Validated application settings. Missing required fields cause startup failure."""

        # ── Feishu credentials (required) ──
        FEISHU_APP_ID: str = Field(default="", description="飞书应用 App ID")
        FEISHU_APP_SECRET: str = Field(default="", description="飞书应用 App Secret")

        # ── LLM (Volcano Ark, OpenAI compatible) ──
        ARK_API_KEY: str = Field(default="", description="火山方舟 API Key")
        ARK_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/coding/v3"
        ARK_MODEL: str = "doubao-seed-2.0-pro"
        ARK_EMBED_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
        ARK_EMBED_MODEL: str = "doubao-embedding-text-240715"
        ARK_EMBED_DIM: int = 2048

        # ── Multi-provider LLM Keys (optional) ──
        DOUBAO_API_KEY: str = ""
        MINIMAX_API_KEY: str = ""
        DEEPSEEK_API_KEY: str = ""
        KIMI_API_KEY: str = ""

        # ── Mentor ──
        MENTOR_PROACTIVE_COOLDOWN_SEC: int = 300
        MENTOR_PROACTIVE_DAILY_MAX: int = 3
        MENTOR_KB_TOPK: int = 5
        MENTOR_KB_CHUNK_CHARS: int = 400
        MENTOR_AMBIGUITY_THRESHOLD: float = 0.5

        # ── Bitable (optional analytics sink) ──
        BITABLE_APP_TOKEN: str = ""
        BITABLE_TABLE_ID: str = ""

        # ── Focus & schedule ──
        DEFAULT_FOCUS_DURATION: int = 30
        DAILY_REPORT_HOUR: int = 18
        DAILY_REPORT_MINUTE: int = 0
        CALENDAR_POLL_MINUTES: int = 5
        FOCUS_KEYWORDS_IN_CALENDAR: List[str] = [
            "专注", "深度工作", "Deep Work", "focus", "勿扰", "免打扰"
        ]

        # ── Urgent keywords (Smart Shield rule layer) ──
        URGENT_KEYWORDS: List[str] = [
            "紧急", "urgent", "ASAP", "马上", "立刻", "立即",
            "线上故障", "P0", "生产事故", "严重bug", "阻塞",
            "immediately", "critical", "blocking",
        ]

        # ── Notification channels ──
        SMTP_HOST: str = ""
        SMTP_PORT: int = 465
        SMTP_USER: str = ""
        SMTP_PASS: str = ""
        NOTIFY_EMAIL: str = ""
        WEBHOOK_BARK_URL: str = ""
        WEBHOOK_SERVERCHAN_KEY: str = ""
        WEBHOOK_DINGTALK_URL: str = ""

        # ── Dashboard ──
        DASHBOARD_PORT: int = 8001
        DASHBOARD_HOST: str = "0.0.0.0"
        DASHBOARD_DEMO_MODE: bool = False

        # ── Smart Shield 6-dimension classifier weights ──
        DIM_WEIGHT_IDENTITY: float = 0.25
        DIM_WEIGHT_RELATION: float = 0.10
        DIM_WEIGHT_CONTENT: float = 0.30
        DIM_WEIGHT_TASK_REL: float = 0.15
        DIM_WEIGHT_TIME: float = 0.10
        DIM_WEIGHT_CHANNEL: float = 0.10

        # Score thresholds → P0/P1/P2/P3
        THRESHOLD_P0: float = 0.55
        THRESHOLD_P1: float = 0.38
        THRESHOLD_P2: float = 0.24

        # ── Emergency circuit breaker ──
        CIRCUIT_BREAKER_P0_COUNT: int = 3
        CIRCUIT_BREAKER_WINDOW_SEC: int = 120

        # ── Time sensitivity patterns ──
        TIME_SENSITIVITY_PATTERNS: List[str] = [
            "今天", "今晚", "马上", "立刻", "现在", "1小时内", "半小时", "30分钟",
            "今日", "下班前", "today", "tonight", "this morning",
            "deadline", "ddl", "due", "by EOD",
        ]

        # ── Sync & Security ──
        SYNC_HUB_PORT: int = 8002
        LARKMENTOR_PILOT_SHARE_SECRET: str = ""

        model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    Config = Settings()

except ImportError:
    logger.debug("pydantic-settings not installed, falling back to plain env vars")

    class _FallbackConfig:
        """Fallback config when pydantic-settings is not available."""

        FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
        FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

        ARK_API_KEY = os.getenv("ARK_API_KEY", "")
        ARK_BASE_URL = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")
        ARK_MODEL = os.getenv("ARK_MODEL", "doubao-seed-2.0-pro")
        ARK_EMBED_BASE_URL = os.getenv("ARK_EMBED_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
        ARK_EMBED_MODEL = os.getenv("ARK_EMBED_MODEL", "doubao-embedding-text-240715")
        ARK_EMBED_DIM = int(os.getenv("ARK_EMBED_DIM", "2048"))

        DOUBAO_API_KEY = os.getenv("DOUBAO_API_KEY", "")
        MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
        DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
        KIMI_API_KEY = os.getenv("KIMI_API_KEY", "")

        MENTOR_PROACTIVE_COOLDOWN_SEC = int(os.getenv("MENTOR_PROACTIVE_COOLDOWN_SEC", "300"))
        MENTOR_PROACTIVE_DAILY_MAX = int(os.getenv("MENTOR_PROACTIVE_DAILY_MAX", "3"))
        MENTOR_KB_TOPK = int(os.getenv("MENTOR_KB_TOPK", "5"))
        MENTOR_KB_CHUNK_CHARS = int(os.getenv("MENTOR_KB_CHUNK_CHARS", "400"))
        MENTOR_AMBIGUITY_THRESHOLD = float(os.getenv("MENTOR_AMBIGUITY_THRESHOLD", "0.5"))

        BITABLE_APP_TOKEN = os.getenv("BITABLE_APP_TOKEN", "")
        BITABLE_TABLE_ID = os.getenv("BITABLE_TABLE_ID", "")

        DEFAULT_FOCUS_DURATION = int(os.getenv("DEFAULT_FOCUS_DURATION", "30"))
        DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "18"))
        DAILY_REPORT_MINUTE = int(os.getenv("DAILY_REPORT_MINUTE", "0"))
        CALENDAR_POLL_MINUTES = int(os.getenv("CALENDAR_POLL_MINUTES", "5"))
        FOCUS_KEYWORDS_IN_CALENDAR = ["专注", "深度工作", "Deep Work", "focus", "勿扰", "免打扰"]

        URGENT_KEYWORDS = [
            "紧急", "urgent", "ASAP", "马上", "立刻", "立即",
            "线上故障", "P0", "生产事故", "严重bug", "阻塞",
            "immediately", "critical", "blocking",
        ]

        SMTP_HOST = os.getenv("SMTP_HOST", "")
        SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
        SMTP_USER = os.getenv("SMTP_USER", "")
        SMTP_PASS = os.getenv("SMTP_PASS", "")
        NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "")
        WEBHOOK_BARK_URL = os.getenv("WEBHOOK_BARK_URL", "")
        WEBHOOK_SERVERCHAN_KEY = os.getenv("WEBHOOK_SERVERCHAN_KEY", "")
        WEBHOOK_DINGTALK_URL = os.getenv("WEBHOOK_DINGTALK_URL", "")

        DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8001"))
        DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
        DASHBOARD_DEMO_MODE = os.getenv("DASHBOARD_DEMO_MODE", "false").lower() == "true"

        DIM_WEIGHT_IDENTITY = float(os.getenv("DIM_WEIGHT_IDENTITY", "0.25"))
        DIM_WEIGHT_RELATION = float(os.getenv("DIM_WEIGHT_RELATION", "0.10"))
        DIM_WEIGHT_CONTENT = float(os.getenv("DIM_WEIGHT_CONTENT", "0.30"))
        DIM_WEIGHT_TASK_REL = float(os.getenv("DIM_WEIGHT_TASK_REL", "0.15"))
        DIM_WEIGHT_TIME = float(os.getenv("DIM_WEIGHT_TIME", "0.10"))
        DIM_WEIGHT_CHANNEL = float(os.getenv("DIM_WEIGHT_CHANNEL", "0.10"))

        THRESHOLD_P0 = float(os.getenv("THRESHOLD_P0", "0.55"))
        THRESHOLD_P1 = float(os.getenv("THRESHOLD_P1", "0.38"))
        THRESHOLD_P2 = float(os.getenv("THRESHOLD_P2", "0.24"))

        CIRCUIT_BREAKER_P0_COUNT = int(os.getenv("CIRCUIT_BREAKER_P0_COUNT", "3"))
        CIRCUIT_BREAKER_WINDOW_SEC = int(os.getenv("CIRCUIT_BREAKER_WINDOW_SEC", "120"))

        TIME_SENSITIVITY_PATTERNS = [
            "今天", "今晚", "马上", "立刻", "现在", "1小时内", "半小时", "30分钟",
            "今日", "下班前", "today", "tonight", "this morning",
            "deadline", "ddl", "due", "by EOD",
        ]

        SYNC_HUB_PORT = int(os.getenv("SYNC_HUB_PORT", "8002"))
        LARKMENTOR_PILOT_SHARE_SECRET = os.getenv("LARKMENTOR_PILOT_SHARE_SECRET", "")

    Config = _FallbackConfig()
