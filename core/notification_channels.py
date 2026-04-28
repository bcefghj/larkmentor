"""Multi-channel notification dispatcher.

A unified abstraction over reachability channels for P0 messages and
critical alerts. Each channel implements a `Channel.send(...)` interface;
the `Dispatcher` selects appropriate channels per priority level.

Implemented channels:
    - FeishuChannel       : the default, via existing Bot card sender
    - EmailChannel        : real SMTP (163.com tested)
    - BarkChannel         : iOS push, optional
    - ServerChanChannel   : WeChat push, optional
    - DingTalkChannel     : DingTalk webhook, optional
    - DesktopChannel      : narrative-only (returns 'reserved') for now

Selection rules:
    - P0 → Feishu + Email + (any configured webhook)
    - P1 → Feishu only
    - P2/P3 → no extra notification (auto-handled by shield)
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional

import requests

from config import Config

logger = logging.getLogger("flowguard.notify")


@dataclass
class NotificationPayload:
    title: str
    body: str
    sender: str = ""
    chat: str = ""
    level: str = "P0"
    extra_url: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class DispatchResult:
    channel: str
    success: bool
    detail: str = ""


class Channel(ABC):
    name = "abstract"

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def send(self, payload: NotificationPayload) -> DispatchResult: ...


# ─── Feishu (handled by existing message_sender) ──

class FeishuChannel(Channel):
    name = "feishu"

    def __init__(self, sender_callable=None):
        self._sender = sender_callable

    def is_available(self) -> bool:
        return self._sender is not None

    def send(self, payload: NotificationPayload) -> DispatchResult:
        if not self._sender:
            return DispatchResult(self.name, False, "no sender bound")
        try:
            self._sender(payload)
            return DispatchResult(self.name, True, "delivered")
        except Exception as e:
            return DispatchResult(self.name, False, str(e))


# ─── Email (real SMTP) ───────────────────────────────────────────

class EmailChannel(Channel):
    name = "email"

    def is_available(self) -> bool:
        return bool(
            Config.SMTP_HOST and Config.SMTP_USER and
            Config.SMTP_PASS and Config.NOTIFY_EMAIL
        )

    def send(self, payload: NotificationPayload) -> DispatchResult:
        if not self.is_available():
            return DispatchResult(self.name, False, "email not configured")
        try:
            msg = MIMEMultipart()
            msg["From"] = Header(f"LarkMentor <{Config.SMTP_USER}>", "utf-8")
            msg["To"] = Config.NOTIFY_EMAIL
            msg["Subject"] = Header(
                f"[LarkMentor {payload.level}] {payload.title}", "utf-8"
            )

            html = self._build_html(payload)
            msg.attach(MIMEText(html, "html", "utf-8"))

            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                Config.SMTP_HOST, Config.SMTP_PORT, context=ctx, timeout=10
            ) as s:
                s.login(Config.SMTP_USER, Config.SMTP_PASS)
                s.sendmail(Config.SMTP_USER, [Config.NOTIFY_EMAIL], msg.as_string())
            logger.info("Email sent to %s [%s]", Config.NOTIFY_EMAIL, payload.level)
            return DispatchResult(self.name, True, "sent")
        except Exception as e:
            logger.error("Email send failed: %s", e)
            return DispatchResult(self.name, False, str(e))

    def _build_html(self, p: NotificationPayload) -> str:
        color = {"P0": "#E11D48", "P1": "#F59E0B", "P2": "#3B82F6"}.get(p.level, "#64748B")
        return f"""
        <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                    max-width:560px;margin:24px auto;border:1px solid #E5E7EB;
                    border-radius:12px;overflow:hidden;">
          <div style="background:{color};color:#fff;padding:14px 20px;font-weight:600;">
            LarkMentor 紧急转达 · {p.level}
          </div>
          <div style="padding:20px;color:#0F172A;line-height:1.6;">
            <p style="margin:0 0 8px 0;font-size:14px;color:#64748B;">
              来自 <strong>{p.sender or '未知'}</strong> · 在 {p.chat or '私聊'}
            </p>
            <h2 style="margin:8px 0 12px 0;font-size:18px;">{p.title}</h2>
            <div style="background:#F8FAFC;padding:12px 14px;border-radius:8px;
                        white-space:pre-wrap;font-size:14px;">{p.body}</div>
            {f'<p style="margin-top:16px;"><a href="{p.extra_url}" style="color:#3370FF;text-decoration:none;">在飞书中查看 →</a></p>' if p.extra_url else ''}
          </div>
          <div style="padding:12px 20px;background:#F8FAFC;color:#94A3B8;
                      font-size:12px;text-align:center;border-top:1px solid #E5E7EB;">
            此邮件由 LarkMentor Agent 自动发送，仅用于 P0 紧急消息兜底通知
          </div>
        </div>
        """


# ─── Bark (iOS push) ───────────────────────────────────────────

class BarkChannel(Channel):
    name = "bark"

    def is_available(self) -> bool:
        return bool(Config.WEBHOOK_BARK_URL)

    def send(self, payload: NotificationPayload) -> DispatchResult:
        if not self.is_available():
            return DispatchResult(self.name, False, "bark not configured")
        try:
            url = f"{Config.WEBHOOK_BARK_URL.rstrip('/')}/{payload.title}/{payload.body[:200]}"
            params = {"level": "timeSensitive" if payload.level == "P0" else "active"}
            r = requests.get(url, params=params, timeout=5)
            return DispatchResult(self.name, r.ok, f"http {r.status_code}")
        except Exception as e:
            return DispatchResult(self.name, False, str(e))


# ─── Server酱 (WeChat push) ──────────────────────────────────

class ServerChanChannel(Channel):
    name = "serverchan"

    def is_available(self) -> bool:
        return bool(Config.WEBHOOK_SERVERCHAN_KEY)

    def send(self, payload: NotificationPayload) -> DispatchResult:
        if not self.is_available():
            return DispatchResult(self.name, False, "serverchan not configured")
        try:
            url = f"https://sctapi.ftqq.com/{Config.WEBHOOK_SERVERCHAN_KEY}.send"
            r = requests.post(url, data={"title": f"[LarkMentor {payload.level}] {payload.title}",
                                          "desp": payload.body}, timeout=5)
            return DispatchResult(self.name, r.ok, f"http {r.status_code}")
        except Exception as e:
            return DispatchResult(self.name, False, str(e))


# ─── DingTalk Webhook ──────────────────────────────────────────

class DingTalkChannel(Channel):
    name = "dingtalk"

    def is_available(self) -> bool:
        return bool(Config.WEBHOOK_DINGTALK_URL)

    def send(self, payload: NotificationPayload) -> DispatchResult:
        if not self.is_available():
            return DispatchResult(self.name, False, "dingtalk not configured")
        try:
            data = {"msgtype": "markdown", "markdown": {
                "title": f"LarkMentor {payload.level}: {payload.title}",
                "text": f"### [{payload.level}] {payload.title}\n来自：{payload.sender}\n\n{payload.body}",
            }}
            r = requests.post(Config.WEBHOOK_DINGTALK_URL, json=data, timeout=5)
            return DispatchResult(self.name, r.ok, f"http {r.status_code}")
        except Exception as e:
            return DispatchResult(self.name, False, str(e))


# ─── Desktop (narrative reserve) ───────────────────────────────

class DesktopChannel(Channel):
    name = "desktop"

    def is_available(self) -> bool:
        return False  # not implemented in headless server

    def send(self, payload: NotificationPayload) -> DispatchResult:
        return DispatchResult(self.name, False, "reserved (narrative only)")


# ─── Dispatcher ─────────────────────────────────────────────────

class Dispatcher:
    """Selects channels by level and dispatches the payload."""

    def __init__(self, channels: List[Channel]):
        self.channels = channels

    def dispatch(self, payload: NotificationPayload) -> List[DispatchResult]:
        results: List[DispatchResult] = []
        for ch in self._select(payload.level):
            if not ch.is_available():
                continue
            r = ch.send(payload)
            results.append(r)
        return results

    def _select(self, level: str) -> List[Channel]:
        if level == "P0":
            return self.channels  # all available
        if level == "P1":
            return [c for c in self.channels if c.name == "feishu"]
        return []


# ─── Factory ───────────────────────────────────────────────────

_dispatcher: Optional[Dispatcher] = None


def init_dispatcher(feishu_sender_callable=None) -> Dispatcher:
    global _dispatcher
    _dispatcher = Dispatcher([
        FeishuChannel(sender_callable=feishu_sender_callable),
        EmailChannel(),
        BarkChannel(),
        ServerChanChannel(),
        DingTalkChannel(),
        DesktopChannel(),
    ])
    available = [c.name for c in _dispatcher.channels if c.is_available()]
    logger.info("Notification channels available: %s", available)
    return _dispatcher


def get_dispatcher() -> Optional[Dispatcher]:
    return _dispatcher


def notify(payload: NotificationPayload) -> List[DispatchResult]:
    if _dispatcher is None:
        init_dispatcher()
    return _dispatcher.dispatch(payload)
