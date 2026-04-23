"""Feishu AppLink generator.

AppLink 是飞书客户端深链协议。在我们的场景里，H5 Dashboard 生成的分享卡片
需要在飞书里一点直接打开移动端 WebView / 桌面端原生窗口，这就要用 AppLink。

常用子协议：
  applink://client/web_app/open?appId=<bot_app_id>&mode=<sidebar|window>&path=<h5_path>
  applink://client/message/send_to?open_chat_id=<chat_id>&text=<urlencoded>
  applink://client/chat/open?openChatId=<chat_id>

对应飞书开放文档 2026-01 版：https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Dict, Optional


def build_open_h5(*, h5_path: str, mode: str = "window",
                  app_id: Optional[str] = None, extra: Optional[Dict[str, str]] = None) -> str:
    """Generate an applink that opens an H5 page inside Feishu."""
    params = {
        "appId": app_id or os.getenv("FEISHU_APP_ID", ""),
        "mode": mode,
        "path": h5_path,
    }
    if extra:
        params.update({k: str(v) for k, v in extra.items()})
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v})
    return f"applink://client/web_app/open?{qs}"


def build_chat_open(chat_id: str) -> str:
    return f"applink://client/chat/open?openChatId={urllib.parse.quote(chat_id)}"


def build_send_to(*, chat_id: str, text: str) -> str:
    params = {"open_chat_id": chat_id, "text": text}
    return f"applink://client/message/send_to?{urllib.parse.urlencode(params)}"


def pilot_plan_applink(plan_id: str, *, dashboard_base: Optional[str] = None) -> str:
    """Applink that jumps into the Dashboard pilot detail view."""
    base = dashboard_base or os.getenv("LARKMENTOR_DASHBOARD_URL", "http://118.178.242.26/dashboard/pilot")
    # AppLink path is a relative URL from the H5 root, not the full URL.
    # We expose ``plan=<plan_id>`` as a query param our SPA handles.
    return build_open_h5(
        h5_path=f"/dashboard/pilot?plan={urllib.parse.quote(plan_id)}",
        mode="window",
        extra={"_base": base},
    )
