"""Feishu SDK client singleton."""

import logging
import lark_oapi as lark

from config import Config

logger = logging.getLogger("flowguard.feishu")

_client: "lark.Client" = None


def get_client() -> lark.Client:
    global _client
    if _client is None:
        _client = (
            lark.Client.builder()
            .app_id(Config.FEISHU_APP_ID)
            .app_secret(Config.FEISHU_APP_SECRET)
            .log_level(lark.LogLevel.INFO)
            .build()
        )
    return _client
