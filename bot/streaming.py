"""Feishu Card streaming writer — typewriter effect via card patches.

Uses the Feishu Interactive Message Card API to update card content
progressively, creating a typewriter effect similar to ChatGPT's streaming
responses.

Protocol
--------
1. ``start()`` sends an initial card with placeholder content and returns
   the ``message_id`` used for subsequent patches.
2. ``append()`` buffers text chunks. A background timer coalesces buffered
   chunks into a single PATCH every ``batch_interval`` seconds so we stay
   well within Feishu's rate limits (~5 QPS per message).
3. ``finish()`` sends a final card update with the complete content and
   optional action buttons.
4. ``error()`` replaces the card with an error-state card.

Thread-safety
-------------
All public methods are safe to call from any thread. Internal state is
protected by a ``threading.Lock``.

Rate-limiting
-------------
Feishu allows roughly 5 card-update RPCs per message per second. The
default ``batch_interval=0.3s`` yields ~3.3 updates/s, leaving headroom.
If a PATCH returns HTTP 429, the writer backs off exponentially (capped
at 5 s) before retrying up to ``max_retries`` times.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import cards_streaming
from .feishu_client import get_client, get_tenant_access_token
from .message_sender import patch_card, send_card

logger = logging.getLogger("bot.streaming")


@dataclass
class _StreamState:
    """Mutable internal state guarded by CardStreamWriter._lock."""

    message_id: str = ""
    chat_id: str = ""
    title: str = ""
    task_id: str = ""
    buffer: str = ""
    flushed_text: str = ""
    started_at: float = 0.0
    progress: float = 0.0
    current_step: str = ""
    status: str = "streaming"
    finished: bool = False
    patch_count: int = 0
    consecutive_failures: int = 0


class CardStreamWriter:
    """Feishu Card streaming writer — implements typewriter effect via card patches.

    Uses Feishu Interactive Message Card API to update card content progressively,
    creating a typewriter effect similar to ChatGPT's streaming responses.

    Protocol:
    1. Send initial card with placeholder content
    2. Periodically PATCH the card's markdown element with accumulated text
    3. Final update marks streaming as complete
    """

    def __init__(
        self,
        *,
        batch_interval: float = 0.3,
        max_retries: int = 3,
        id_type: str = "open_id",
    ) -> None:
        self._batch_interval = max(0.1, batch_interval)
        self._max_retries = max_retries
        self._id_type = id_type
        self._lock = threading.Lock()
        self._state = _StreamState()
        self._timer: Optional[threading.Timer] = None
        self._flush_event = threading.Event()

    # ── Public API ────────────────────────────────────────────────────────

    def start(
        self,
        chat_id: str,
        initial_title: str,
        *,
        task_id: str = "",
        initial_step: str = "",
    ) -> str:
        """Send the initial progress card and return its ``message_id``.

        The returned ``message_id`` is used internally for all subsequent
        PATCH calls.  Callers may also store it for external tracking.
        """
        with self._lock:
            self._state = _StreamState(
                chat_id=chat_id,
                title=initial_title,
                task_id=task_id,
                started_at=time.time(),
                current_step=initial_step or "准备中",
                status="streaming",
            )

        card = cards_streaming.streaming_progress_card(
            title=initial_title,
            current_text="▋",
            progress_pct=0.0,
            status="streaming",
            task_id=task_id,
            current_step=initial_step or "准备中",
        )

        message_id = self._send_initial_card(chat_id, card)
        with self._lock:
            self._state.message_id = message_id

        self._schedule_flush()
        return message_id

    def append(self, text_chunk: str) -> None:
        """Buffer a text chunk for the next batched PATCH.

        Chunks are coalesced and flushed every ``batch_interval`` seconds
        to avoid hammering the Feishu API.
        """
        if not text_chunk:
            return
        with self._lock:
            if self._state.finished:
                return
            self._state.buffer += text_chunk

    def set_progress(self, progress: float, step: str = "") -> None:
        """Update the progress bar and step label on next flush."""
        with self._lock:
            self._state.progress = max(0.0, min(1.0, progress))
            if step:
                self._state.current_step = step

    def set_status(self, status: str) -> None:
        """Update the card status label on next flush."""
        with self._lock:
            self._state.status = status

    def finish(
        self,
        final_content: Optional[str] = None,
        actions: Optional[List[Dict[str, Any]]] = None,
        *,
        artifacts: Optional[List[Dict[str, str]]] = None,
        summary: str = "",
    ) -> bool:
        """Send the final card with complete content and optional buttons.

        Returns True if the final PATCH succeeded.
        """
        self._cancel_timer()

        with self._lock:
            self._state.finished = True
            if final_content is not None:
                self._state.flushed_text = final_content
            else:
                self._state.flushed_text += self._state.buffer
            self._state.buffer = ""
            elapsed = time.time() - self._state.started_at

            card = cards_streaming.streaming_complete_card(
                title=self._state.title,
                content=self._state.flushed_text,
                artifacts=artifacts,
                actions=actions,
                task_id=self._state.task_id,
                elapsed_sec=elapsed,
                summary=summary,
            )
            message_id = self._state.message_id

        if not message_id:
            logger.warning("finish() called but no message_id — initial card was never sent")
            return False

        return self._patch_with_retry(message_id, card)

    def error(self, error_msg: str, *, detail: str = "") -> bool:
        """Replace the card content with an error state.

        Returns True if the PATCH succeeded.
        """
        self._cancel_timer()

        with self._lock:
            self._state.finished = True
            self._state.status = "error"

            card = cards_streaming.streaming_error_card(
                title=self._state.title,
                error_msg=error_msg,
                task_id=self._state.task_id,
                detail=detail,
            )
            message_id = self._state.message_id

        if not message_id:
            logger.warning("error() called but no message_id")
            return False

        return self._patch_with_retry(message_id, card)

    @property
    def message_id(self) -> str:
        with self._lock:
            return self._state.message_id

    @property
    def elapsed(self) -> float:
        with self._lock:
            if self._state.started_at <= 0:
                return 0.0
            return time.time() - self._state.started_at

    # ── Batched flush loop ────────────────────────────────────────────────

    def _schedule_flush(self) -> None:
        """Schedule the next batched flush after ``batch_interval``."""
        with self._lock:
            if self._state.finished:
                return
        self._timer = threading.Timer(self._batch_interval, self._flush)
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer(self) -> None:
        t = self._timer
        if t is not None:
            t.cancel()
        self._timer = None

    def _flush(self) -> None:
        """Flush buffered text into a single PATCH call."""
        with self._lock:
            if self._state.finished:
                return
            if not self._state.buffer and self._state.patch_count > 0:
                self._schedule_flush()
                return

            self._state.flushed_text += self._state.buffer
            self._state.buffer = ""
            elapsed = time.time() - self._state.started_at

            card = cards_streaming.streaming_progress_card(
                title=self._state.title,
                current_text=self._state.flushed_text + "▋",
                progress_pct=self._state.progress,
                status=self._state.status,
                task_id=self._state.task_id,
                current_step=self._state.current_step,
                elapsed_sec=elapsed,
            )
            message_id = self._state.message_id

        if message_id:
            ok = self._patch_with_retry(message_id, card)
            with self._lock:
                if ok:
                    self._state.patch_count += 1
                    self._state.consecutive_failures = 0
                else:
                    self._state.consecutive_failures += 1

        self._schedule_flush()

    # ── Low-level send / patch ────────────────────────────────────────────

    def _send_initial_card(self, chat_id: str, card: Dict[str, Any]) -> str:
        """Send the initial card and return the message_id."""
        client = get_client()
        try:
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest,
                CreateMessageRequestBody,
            )

            body = (
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .content(json.dumps(card))
                .msg_type("interactive")
                .build()
            )
            req = CreateMessageRequest.builder().receive_id_type(self._id_type).request_body(body).build()
            resp = client.im.v1.message.create(req)
            if resp.success() and resp.data and resp.data.message_id:
                logger.debug("initial card sent, message_id=%s", resp.data.message_id)
                return resp.data.message_id
            logger.error("initial card send failed: code=%d msg=%s", resp.code, resp.msg)
        except Exception:
            logger.exception("initial card send exception")

        return f"fallback-{int(time.time() * 1000)}"

    def _patch_with_retry(self, message_id: str, card: Dict[str, Any]) -> bool:
        """PATCH a card with exponential back-off on 429 / transient errors."""
        backoff = 0.5
        for attempt in range(1, self._max_retries + 1):
            ok = self._do_patch(message_id, card)
            if ok:
                return True
            if attempt < self._max_retries:
                logger.info(
                    "patch retry %d/%d after %.1fs backoff (msg=%s)",
                    attempt,
                    self._max_retries,
                    backoff,
                    message_id,
                )
                time.sleep(backoff)
                backoff = min(5.0, backoff * 2)
        return False

    @staticmethod
    def _do_patch(message_id: str, card: Dict[str, Any]) -> bool:
        """Single PATCH attempt via lark-oapi SDK."""
        return patch_card(message_id, card)


__all__ = ["CardStreamWriter"]
