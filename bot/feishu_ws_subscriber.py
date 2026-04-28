"""Feishu WebSocket long-connection subscriber (P2.5).

Runs in parallel with the HTTP Webhook path. When ``LARKMENTOR_WS_ENABLED=1``
the process opens a persistent WS using ``lark-oapi`` and dispatches the same
events ``bot/event_handler.py`` handles over Webhook. This removes the need
for a public callback URL, which matters for judges demoing on WiFi.

Design notes
------------

- **Coexistence with Webhook** — events are keyed by ``event_id`` in a 5-min
  TTL set. Whichever channel arrives first wins; the other is dropped. Set
  ``LARKMENTOR_WS_EXCLUSIVE=1`` to disable webhook dispatch entirely.
- **Backoff** — on disconnect we reconnect with capped exponential backoff
  (2s → 4s → 8s → 30s). The SDK does most of this, but we wrap it so log
  lines stay readable.
- **Graceful shutdown** — a ``threading.Event`` is honoured so the WS thread
  exits cleanly when the FastAPI app is reloaded.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Optional, Set

logger = logging.getLogger("larkmentor.feishu.ws")


class _EventDedup:
    """Tiny TTL set for event_id dedupe; thread-safe."""

    def __init__(self, ttl_sec: int = 300) -> None:
        self.ttl = ttl_sec
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def seen(self, event_id: str) -> bool:
        if not event_id:
            return False
        now = time.time()
        with self._lock:
            self._gc(now)
            if event_id in self._seen:
                return True
            self._seen[event_id] = now
            return False

    def _gc(self, now: float) -> None:
        cutoff = now - self.ttl
        dead = [k for k, ts in self._seen.items() if ts < cutoff]
        for k in dead:
            self._seen.pop(k, None)


DEDUP = _EventDedup()


def is_dup(event_id: str) -> bool:
    """Public helper used by ``bot.event_handler`` Webhook path too."""
    return DEDUP.seen(event_id)


class FeishuLongConnection:
    """Thin wrapper over lark-oapi WsClient for our event bus."""

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        on_p2_message_receive_v1: Optional[Callable[[Any], None]] = None,
        on_p2_card_action_trigger: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self._on_msg = on_p2_message_receive_v1
        self._on_card = on_p2_card_action_trigger
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._backoff = 2.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_forever,
            name="feishu-ws",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self._open_and_block()
                self._backoff = 2.0
            except Exception as e:
                logger.warning("WS disconnected: %s; reconnect in %.0fs", e, self._backoff)
                time.sleep(self._backoff)
                self._backoff = min(30.0, self._backoff * 2)

    def _open_and_block(self) -> None:
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
            from lark_oapi.api.callback import P2CardActionTrigger
        except Exception as e:
            raise RuntimeError(f"lark-oapi WsClient unavailable: {e}") from e

        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._dispatch_msg)
            .register_p2_card_action_trigger(self._dispatch_card)
            .build()
        )
        cli = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.INFO,
        )
        logger.info("Feishu WS connecting app_id=%s****", self.app_id[:4])
        cli.start()
        while not self._stop.is_set():
            time.sleep(1)
        try:
            cli.stop()
        except Exception:
            pass

    def _dispatch_msg(self, data: Any) -> None:
        try:
            eid = getattr(getattr(data, "header", None), "event_id", "")
            if is_dup(eid):
                logger.debug("WS event %s dedup-skip", eid)
                return
            if self._on_msg:
                self._on_msg(data)
        except Exception as e:
            logger.exception("WS msg handler error: %s", e)

    def _dispatch_card(self, data: Any) -> Any:
        try:
            if self._on_card:
                return self._on_card(data)
        except Exception as e:
            logger.exception("WS card handler error: %s", e)
        return None


_SINGLETON: Optional[FeishuLongConnection] = None


def start_long_connection() -> Optional[FeishuLongConnection]:
    """Idempotently starts the WS client if ``LARKMENTOR_WS_ENABLED=1``.

    Returns the singleton for introspection (stop / metrics)."""
    global _SINGLETON
    if os.getenv("LARKMENTOR_WS_ENABLED", "0") != "1":
        logger.info("WS subscriber disabled (LARKMENTOR_WS_ENABLED!=1)")
        return None
    if _SINGLETON:
        return _SINGLETON
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    if not (app_id and app_secret):
        logger.warning("WS subscriber needs FEISHU_APP_ID + FEISHU_APP_SECRET")
        return None
    try:
        from bot.event_handler import on_message_receive, on_card_action
    except Exception as e:
        logger.warning("WS subscriber cannot import event_handler: %s", e)
        return None

    _SINGLETON = FeishuLongConnection(
        app_id=app_id,
        app_secret=app_secret,
        on_p2_message_receive_v1=on_message_receive,
        on_p2_card_action_trigger=on_card_action,
    )
    _SINGLETON.start()
    return _SINGLETON
