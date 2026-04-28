"""Three-tier urgent notification (im:message.urgent_app / sms / phone)."""

from __future__ import annotations

import logging
from typing import Dict, List

from core.security.audit_log import audit
from core.security.permission_manager import default_manager

logger = logging.getLogger("flowguard.feishu.urgent")


def _send(message_id: str, open_ids: List[str], kind: str, *, actor: str) -> Dict:
    """Common dispatcher across urgent_app / urgent_sms / urgent_phone."""
    tool = f"shield.urgent_{kind}"
    decision = default_manager().check(tool=tool, user_open_id=actor)
    if not decision.allowed:
        audit(actor=actor, action=tool, resource=message_id, outcome="deny",
              severity="WARN", meta={"reason": decision.reason, "kind": kind})
        return {"ok": False, "reason": decision.reason}

    try:
        from bot.feishu_client import get_client
        from lark_oapi.api.im.v1 import (  # type: ignore
            UrgentAppMessageRequest, UrgentSmsMessageRequest, UrgentPhoneMessageRequest,
            UrgentAppMessageRequestBody, UrgentSmsMessageRequestBody, UrgentPhoneMessageRequestBody,
        )
        client = get_client()
        if kind == "app":
            req = (
                UrgentAppMessageRequest.builder()
                .message_id(message_id).user_id_type("open_id")
                .request_body(UrgentAppMessageRequestBody.builder().user_id_list(open_ids).build())
                .build()
            )
            resp = client.im.v1.message.urgent_app(req)
        elif kind == "sms":
            req = (
                UrgentSmsMessageRequest.builder()
                .message_id(message_id).user_id_type("open_id")
                .request_body(UrgentSmsMessageRequestBody.builder().user_id_list(open_ids).build())
                .build()
            )
            resp = client.im.v1.message.urgent_sms(req)
        else:  # phone
            req = (
                UrgentPhoneMessageRequest.builder()
                .message_id(message_id).user_id_type("open_id")
                .request_body(UrgentPhoneMessageRequestBody.builder().user_id_list(open_ids).build())
                .build()
            )
            resp = client.im.v1.message.urgent_phone(req)
        ok = resp.success()
        audit(actor=actor, action=tool, resource=message_id,
              outcome="allow" if ok else "error",
              severity="HIGH" if kind == "phone" else "WARN",
              meta={"kind": kind, "targets": ",".join(o[-6:] for o in open_ids)})
        return {"ok": ok, "code": getattr(resp, "code", None), "msg": getattr(resp, "msg", None)}
    except Exception as e:
        logger.warning("urgent_%s error: %s", kind, e)
        audit(actor=actor, action=tool, resource=message_id, outcome="error",
              severity="WARN", meta={"error": str(e)})
        return {"ok": False, "error": str(e)}


def send_urgent_app(message_id: str, open_ids: List[str], *, actor: str) -> Dict:
    return _send(message_id, open_ids, "app", actor=actor)


def send_urgent_sms(message_id: str, open_ids: List[str], *, actor: str) -> Dict:
    return _send(message_id, open_ids, "sms", actor=actor)


def send_urgent_phone(message_id: str, open_ids: List[str], *, actor: str) -> Dict:
    return _send(message_id, open_ids, "phone", actor=actor)
