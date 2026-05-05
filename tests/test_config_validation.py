"""Tests for config.py — Pydantic validation and defaults."""


class TestConfigDefaults:
    """Verify all default values are sane."""

    def test_feishu_fields_exist(self):
        from config import Config

        assert hasattr(Config, "FEISHU_APP_ID")
        assert hasattr(Config, "FEISHU_APP_SECRET")

    def test_ark_defaults(self):
        from config import Config

        assert "volces.com" in Config.ARK_BASE_URL
        assert Config.ARK_MODEL == "doubao-seed-2.0-pro"
        assert Config.ARK_EMBED_DIM == 2048

    def test_mentor_defaults(self):
        from config import Config

        assert Config.MENTOR_PROACTIVE_COOLDOWN_SEC == 300
        assert Config.MENTOR_PROACTIVE_DAILY_MAX == 3
        assert 0 < Config.MENTOR_AMBIGUITY_THRESHOLD < 1

    def test_dashboard_defaults(self):
        from config import Config

        assert isinstance(Config.DASHBOARD_PORT, int)
        assert Config.DASHBOARD_PORT > 0
        assert Config.DASHBOARD_HOST == "0.0.0.0"

    def test_shield_weights_sum_to_one(self):
        from config import Config

        total = (
            Config.DIM_WEIGHT_IDENTITY
            + Config.DIM_WEIGHT_RELATION
            + Config.DIM_WEIGHT_CONTENT
            + Config.DIM_WEIGHT_TASK_REL
            + Config.DIM_WEIGHT_TIME
            + Config.DIM_WEIGHT_CHANNEL
        )
        assert abs(total - 1.0) < 0.01

    def test_threshold_ordering(self):
        from config import Config

        assert Config.THRESHOLD_P0 > Config.THRESHOLD_P1 > Config.THRESHOLD_P2

    def test_circuit_breaker_defaults(self):
        from config import Config

        assert Config.CIRCUIT_BREAKER_P0_COUNT == 3
        assert Config.CIRCUIT_BREAKER_WINDOW_SEC == 120

    def test_urgent_keywords_nonempty(self):
        from config import Config

        assert len(Config.URGENT_KEYWORDS) > 5
        assert "紧急" in Config.URGENT_KEYWORDS

    def test_time_sensitivity_patterns(self):
        from config import Config

        assert len(Config.TIME_SENSITIVITY_PATTERNS) > 5
        assert "今天" in Config.TIME_SENSITIVITY_PATTERNS

    def test_focus_keywords(self):
        from config import Config

        assert "专注" in Config.FOCUS_KEYWORDS_IN_CALENDAR
        assert "Deep Work" in Config.FOCUS_KEYWORDS_IN_CALENDAR

    def test_sync_hub_port(self):
        from config import Config

        assert Config.SYNC_HUB_PORT == 8002
