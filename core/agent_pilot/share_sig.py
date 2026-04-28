"""HMAC signature helper for Pilot Plan share links (P1.6).

Share URL structure::

    http://host/pilot/<plan_id>?sig=<base64_hmac>&exp=<unix_ts>

Verification rejects expired or tampered URLs. Secret comes from
``LARKMENTOR_PILOT_SHARE_SECRET``; when absent, the server allows legacy
open access (local dev only).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from typing import Dict


def _secret() -> str:
    return os.getenv("LARKMENTOR_PILOT_SHARE_SECRET", "")


def sign(plan_id: str, *, exp_ts: int, secret: str = "") -> str:
    key = (secret or _secret()).encode("utf-8")
    if not key:
        return ""
    msg = f"{plan_id}|{exp_ts}".encode("utf-8")
    mac = hmac.new(key, msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def verify(plan_id: str, sig: str, *, secret: str = "") -> bool:
    """Accepts `sig = <base64>.<exp_ts>`. Returns False on any mismatch."""
    if not sig:
        return False
    try:
        encoded, _, exp_s = sig.partition(".")
        exp_ts = int(exp_s or 0)
    except Exception:
        return False
    if exp_ts and exp_ts < int(time.time()):
        return False
    expected = sign(plan_id, exp_ts=exp_ts, secret=secret)
    if not expected:
        return False
    return hmac.compare_digest(expected, encoded)


def sign_url(plan_id: str, *, base_path: str = "", ttl_sec: int = 7 * 86400,
             secret: str = "") -> Dict[str, str]:
    """Generate a full URL with sig=<mac>.<exp_ts>."""
    exp_ts = int(time.time()) + ttl_sec
    mac = sign(plan_id, exp_ts=exp_ts, secret=secret)
    sig_field = f"{mac}.{exp_ts}" if mac else ""
    path = base_path or f"/pilot/{plan_id}"
    sep = "&" if "?" in path else "?"
    signed = f"{path}{sep}sig={sig_field}" if sig_field else path
    return {
        "plan_id": plan_id,
        "url": signed,
        "exp_ts": exp_ts,
        "signed": bool(sig_field),
    }
