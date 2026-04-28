"""Feishu SDK client singleton + token helpers."""

import json
import logging
import threading
import time
import urllib.request
import urllib.error

import lark_oapi as lark

from config import Config

logger = logging.getLogger("flowguard.feishu")

_client: "lark.Client" = None

# Simple in-memory tenant_access_token cache (2h TTL default).
_TAT_LOCK = threading.Lock()
_TAT_CACHE = {"token": "", "expire_ts": 0}


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


def get_tenant_access_token() -> str:
    """Return a cached tenant_access_token, refreshing when near expiry.

    Used by raw HTTP fallbacks (Board API, custom endpoints) where the
    typed SDK does not yet expose a binding.
    """
    now = int(time.time())
    with _TAT_LOCK:
        if _TAT_CACHE["token"] and _TAT_CACHE["expire_ts"] - now > 60:
            return _TAT_CACHE["token"]
        if not (Config.FEISHU_APP_ID and Config.FEISHU_APP_SECRET):
            return ""
        try:
            req = urllib.request.Request(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                data=json.dumps({
                    "app_id": Config.FEISHU_APP_ID,
                    "app_secret": Config.FEISHU_APP_SECRET,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                body = json.loads(r.read().decode("utf-8"))
            token = body.get("tenant_access_token", "")
            expire = int(body.get("expire", 7200))
            _TAT_CACHE["token"] = token
            _TAT_CACHE["expire_ts"] = now + max(60, expire - 60)
            return token
        except Exception as exc:
            logger.warning("tenant_access_token fetch failed: %s", exc)
            return ""
