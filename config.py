"""FlowGuard runtime configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Feishu credentials ──
    FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
    FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

    # ── LLM (Volcano Ark, OpenAI compatible) ──
    ARK_API_KEY = os.getenv("ARK_API_KEY", "")
    ARK_BASE_URL = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")
    ARK_MODEL = os.getenv("ARK_MODEL", "doubao-seed-2.0-pro")
    # v4: Doubao embedding endpoint (separate from chat base url)
    ARK_EMBED_BASE_URL = os.getenv("ARK_EMBED_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    ARK_EMBED_MODEL = os.getenv("ARK_EMBED_MODEL", "doubao-embedding-text-240715")
    ARK_EMBED_DIM = int(os.getenv("ARK_EMBED_DIM", "2048"))

    # ── v4 Mentor (Rookie Buddy upgrade) ──
    MENTOR_PROACTIVE_COOLDOWN_SEC = int(os.getenv("MENTOR_PROACTIVE_COOLDOWN_SEC", "300"))
    MENTOR_PROACTIVE_DAILY_MAX = int(os.getenv("MENTOR_PROACTIVE_DAILY_MAX", "3"))
    MENTOR_KB_TOPK = int(os.getenv("MENTOR_KB_TOPK", "5"))
    MENTOR_KB_CHUNK_CHARS = int(os.getenv("MENTOR_KB_CHUNK_CHARS", "400"))
    MENTOR_AMBIGUITY_THRESHOLD = float(os.getenv("MENTOR_AMBIGUITY_THRESHOLD", "0.5"))

    # ── Bitable (optional analytics sink) ──
    BITABLE_APP_TOKEN = os.getenv("BITABLE_APP_TOKEN", "")
    BITABLE_TABLE_ID = os.getenv("BITABLE_TABLE_ID", "")

    # ── Focus & schedule ──
    DEFAULT_FOCUS_DURATION = int(os.getenv("DEFAULT_FOCUS_DURATION", "30"))
    DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "18"))
    DAILY_REPORT_MINUTE = int(os.getenv("DAILY_REPORT_MINUTE", "0"))
    CALENDAR_POLL_MINUTES = int(os.getenv("CALENDAR_POLL_MINUTES", "5"))
    FOCUS_KEYWORDS_IN_CALENDAR = ["专注", "深度工作", "Deep Work", "focus", "勿扰", "免打扰"]

    # ── Urgent keywords (Smart Shield rule layer) ──
    URGENT_KEYWORDS = [
        "紧急", "urgent", "ASAP", "马上", "立刻", "立即",
        "线上故障", "P0", "生产事故", "严重bug", "阻塞",
        "immediately", "critical", "blocking",
    ]

    # ── Notification channels (multi-channel touchpoint) ──
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASS = os.getenv("SMTP_PASS", "")
    NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "")

    WEBHOOK_BARK_URL = os.getenv("WEBHOOK_BARK_URL", "")
    WEBHOOK_SERVERCHAN_KEY = os.getenv("WEBHOOK_SERVERCHAN_KEY", "")
    WEBHOOK_DINGTALK_URL = os.getenv("WEBHOOK_DINGTALK_URL", "")

    # ── Dashboard ──
    DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
    DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    DASHBOARD_DEMO_MODE = os.getenv("DASHBOARD_DEMO_MODE", "false").lower() == "true"

    # ── Smart Shield 6-dimension classifier weights ──
    # Sum should ideally be 1.0; each contributes to final urgency score 0-1.
    DIM_WEIGHT_IDENTITY = float(os.getenv("DIM_WEIGHT_IDENTITY", "0.25"))
    DIM_WEIGHT_RELATION = float(os.getenv("DIM_WEIGHT_RELATION", "0.10"))
    DIM_WEIGHT_CONTENT = float(os.getenv("DIM_WEIGHT_CONTENT", "0.30"))
    DIM_WEIGHT_TASK_REL = float(os.getenv("DIM_WEIGHT_TASK_REL", "0.15"))
    DIM_WEIGHT_TIME = float(os.getenv("DIM_WEIGHT_TIME", "0.10"))
    DIM_WEIGHT_CHANNEL = float(os.getenv("DIM_WEIGHT_CHANNEL", "0.10"))

    # Score thresholds → P0/P1/P2/P3
    THRESHOLD_P0 = float(os.getenv("THRESHOLD_P0", "0.55"))
    THRESHOLD_P1 = float(os.getenv("THRESHOLD_P1", "0.38"))
    THRESHOLD_P2 = float(os.getenv("THRESHOLD_P2", "0.24"))

    # ── Emergency circuit breaker ──
    # If N P0 messages within W seconds, auto-exit focus.
    CIRCUIT_BREAKER_P0_COUNT = int(os.getenv("CIRCUIT_BREAKER_P0_COUNT", "3"))
    CIRCUIT_BREAKER_WINDOW_SEC = int(os.getenv("CIRCUIT_BREAKER_WINDOW_SEC", "120"))

    # ── Time sensitivity patterns (regex-friendly substrings) ──
    TIME_SENSITIVITY_PATTERNS = [
        "今天", "今晚", "马上", "立刻", "现在", "1小时内", "半小时", "30分钟",
        "今日", "今晚", "下班前", "today", "tonight", "this morning",
        "deadline", "ddl", "due", "by EOD",
    ]
