"""Agent-Pilot runtime configuration with Pydantic validation.

All settings loaded from environment variables (.env file supported).
Startup fails fast with clear error messages if required fields are missing.
"""

from __future__ import annotations

from typing import List

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()

VERSION = "12.0.0"


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
    MINIMAX_BASE_URL: str = "https://api.minimax.chat/v1"
    MINIMAX_MODEL: str = "MiniMax-M2.7"
    DEEPSEEK_API_KEY: str = ""
    KIMI_API_KEY: str = ""

    # ── MiMo API (小米，主力模型) ──
    MIMO_API_KEY: str = Field(default="", description="小米 MiMo API Key")
    MIMO_BASE_URL: str = "https://token-plan-cn.xiaomimimo.com/v1"
    MIMO_MODEL: str = "mimo-v2.5-pro"

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
    FOCUS_KEYWORDS_IN_CALENDAR: List[str] = ["专注", "深度工作", "Deep Work", "focus", "勿扰", "免打扰"]

    # ── Urgent keywords (Smart Shield rule layer) ──
    URGENT_KEYWORDS: List[str] = [
        "紧急",
        "urgent",
        "ASAP",
        "马上",
        "立刻",
        "立即",
        "线上故障",
        "P0",
        "生产事故",
        "严重bug",
        "阻塞",
        "immediately",
        "critical",
        "blocking",
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
        "今天",
        "今晚",
        "马上",
        "立刻",
        "现在",
        "1小时内",
        "半小时",
        "30分钟",
        "今日",
        "下班前",
        "today",
        "tonight",
        "this morning",
        "deadline",
        "ddl",
        "due",
        "by EOD",
    ]

    # ── Agent-Pilot orchestrator ──
    AGENT_PILOT_DEMO_MODE: bool = False

    # ── Feishu CLI ──
    LARK_CLI_PATH: str = Field(default="lark-cli", description="飞书 CLI 可执行文件路径")
    LARK_CLI_TIMEOUT: int = Field(default=30, description="CLI 命令超时（秒）")

    # ── Sync & Security ──
    SYNC_HUB_PORT: int = 8002
    AGENT_PILOT_SHARE_SECRET: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


Config = Settings()
