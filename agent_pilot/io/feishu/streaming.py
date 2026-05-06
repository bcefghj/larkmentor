"""Streaming progress card – v13 创新点 #2.

Approach: instead of relying on Feishu's elusive cardkit.v1 patch protocol
(which has rough SDK support), we use the simpler ``message.patch`` API to
update an interactive card in place. The bot sends an initial card with a
placeholder, then patches the same message_id every N tokens or every step
boundary, producing a typewriter-like UX.

This module is intentionally lightweight: ``StreamingCardSender`` exposes
``init / patch / finalize`` methods used by the orchestrator.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("agent_pilot.io.feishu.streaming")


class StreamingCardSender:
    """Manage one progress card's lifecycle for a single plan."""

    def __init__(
        self,
        chat_id: str,
        plan_id: str,
        intent: str,
        *,
        flush_interval_sec: float = 1.0,
    ):
        self.chat_id = chat_id
        self.plan_id = plan_id
        self.intent = intent
        self.flush_interval_sec = flush_interval_sec
        self.message_id: str = ""
        self.last_flush_ts: float = 0.0
        self.steps_done: int = 0
        self.steps_total: int = 0
        self.current_step: str = ""
        self.preview: str = ""
        self.artifacts: Dict[str, str] = {}

    # ── API ───────────────────────────────────────────────────────────────────

    def init(self, steps_total: int, progress_url: str = "") -> Optional[str]:
        """Send the initial progress card. Returns message_id or empty string."""
        from agent_pilot.io.feishu.cards.task_card import progress_card

        self.steps_total = steps_total
        card = progress_card(
            plan_id=self.plan_id,
            intent=self.intent,
            steps_done=0,
            steps_total=steps_total,
            current_step="规划中...",
            artifacts={},
            progress_url=progress_url,
        )
        self.message_id = self._send_card(card)
        self.last_flush_ts = time.time()
        return self.message_id

    def update(
        self,
        *,
        steps_done: Optional[int] = None,
        current_step: Optional[str] = None,
        preview_chunk: Optional[str] = None,
        artifact: Optional[Dict[str, str]] = None,
        progress_url: str = "",
        force: bool = False,
    ) -> None:
        """Patch the card with new state. Throttled by flush_interval_sec
        unless ``force=True``."""
        if steps_done is not None:
            self.steps_done = steps_done
        if current_step is not None:
            self.current_step = current_step
        if preview_chunk:
            self.preview += preview_chunk
            self.preview = self.preview[-1200:]  # cap to keep card small
        if artifact:
            self.artifacts.update(artifact)

        now = time.time()
        if not force and (now - self.last_flush_ts) < self.flush_interval_sec:
            return
        self.last_flush_ts = now

        from agent_pilot.io.feishu.cards.task_card import progress_card

        # Append preview as a "current step" suffix so users see streaming output
        cs = self.current_step
        if self.preview:
            cs = f"{cs}\n\n```\n{self.preview[-300:]}\n```"

        card = progress_card(
            plan_id=self.plan_id,
            intent=self.intent,
            steps_done=self.steps_done,
            steps_total=self.steps_total,
            current_step=cs,
            artifacts=self.artifacts,
            progress_url=progress_url,
        )
        if self.message_id:
            self._patch_card(self.message_id, card)
        else:
            self.message_id = self._send_card(card)

    def finalize(
        self,
        *,
        artifacts: Optional[Dict[str, str]] = None,
        summary: str = "",
        progress_url: str = "",
    ) -> None:
        """Replace the progress card with the completion card."""
        if artifacts:
            self.artifacts.update(artifacts)
        from agent_pilot.io.feishu.cards.task_card import completion_card

        card = completion_card(
            plan_id=self.plan_id,
            intent=self.intent,
            artifacts=self.artifacts,
            summary=summary,
            progress_url=progress_url,
        )
        if self.message_id:
            self._patch_card(self.message_id, card)
        else:
            self._send_card(card)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _send_card(self, card: Dict[str, Any]) -> str:
        try:
            from bot.feishu_client import get_client
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest,
                CreateMessageRequestBody,
            )

            client = get_client()
            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(self.chat_id)
                    .msg_type("interactive")
                    .content(json.dumps(card, ensure_ascii=False))
                    .build()
                )
                .build()
            )
            resp = client.im.v1.message.create(req)
            if not resp.success() or not resp.data or not resp.data.message_id:
                logger.warning("streaming card send failed: code=%s msg=%s",
                               getattr(resp, "code", "?"), getattr(resp, "msg", "?"))
                return ""
            return resp.data.message_id
        except Exception as e:
            logger.warning("streaming card send exception: %s", e)
            return ""

    def _patch_card(self, message_id: str, card: Dict[str, Any]) -> None:
        try:
            from bot.feishu_client import get_client
            from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody

            client = get_client()
            req = (
                PatchMessageRequest.builder()
                .message_id(message_id)
                .request_body(
                    PatchMessageRequestBody.builder()
                    .content(json.dumps(card, ensure_ascii=False))
                    .build()
                )
                .build()
            )
            resp = client.im.v1.message.patch(req)
            if not resp.success():
                logger.debug("streaming card patch failed: code=%s msg=%s",
                             getattr(resp, "code", "?"), getattr(resp, "msg", "?"))
        except Exception as e:
            logger.debug("streaming card patch exception: %s", e)


__all__ = ["StreamingCardSender"]
