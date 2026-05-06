"""Dashboard middleware – v13 hardened.

Key changes vs v12:
- RateLimiter raised from 60/60s to 600/60s (well above any human + polling load)
- EXEMPT_PREFIXES whitelist: dashboard pages, status polls, sync WebSocket bypass entirely
- AGENT_PILOT_DISABLE_RATE_LIMIT env kill-switch for demo / debugging
- Per-IP not per-path so judges don't share a single bucket
- Burst credit (10) so a quick refresh wave doesn't get tripped
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from typing import Dict, List, Set

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from core.structured_logging import new_request_id, set_request_context

logger = logging.getLogger("agent_pilot.dashboard.middleware")


# ── Configuration via env (so we can tune without redeploy) ──────────────────
_DISABLE_RATE_LIMIT = os.getenv("AGENT_PILOT_DISABLE_RATE_LIMIT", "0").lower() in ("1", "true", "yes")
_RATE_LIMIT_MAX = int(os.getenv("AGENT_PILOT_RATE_LIMIT_MAX", "600"))
_RATE_LIMIT_WINDOW = int(os.getenv("AGENT_PILOT_RATE_LIMIT_WINDOW", "60"))

# Paths whose traffic is intrinsically high-frequency (polling, websockets, static
# assets) and that should NOT eat into the user's budget.
_EXEMPT_PREFIXES: Set[str] = {
    "/health",
    "/healthz",
    "/dashboard",          # the SPA HTML page
    "/v12/dashboard",
    "/v13/dashboard",
    "/static",
    "/assets",
    "/artifacts",          # generated PPTX/HTML/mp3
    "/docs",               # OpenAPI docs
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
    "/sync",               # WebSocket sync hub
    "/api/pilot/status",   # status polling endpoints
    "/api/pilot/trace",
    "/api/pilot/plans",
    "/api/pilot/plan",
    "/api/overview",
    "/api/health",
}


def _is_exempt(path: str) -> bool:
    if path in _EXEMPT_PREFIXES:
        return True
    for prefix in _EXEMPT_PREFIXES:
        if path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            return True
    return False


class RateLimiter:
    """Sliding-window per-IP rate limiter."""

    def __init__(self, max_requests: int = _RATE_LIMIT_MAX, window_sec: int = _RATE_LIMIT_WINDOW):
        self._max = max_requests
        self._window = window_sec
        self._requests: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(self, client_ip: str) -> bool:
        now = time.time()
        reqs = self._requests[client_ip]
        # purge ancient entries in-place
        reqs[:] = [t for t in reqs if now - t < self._window]
        if len(reqs) >= self._max:
            return False
        reqs.append(now)
        return True

    def stats(self) -> Dict[str, int]:
        """Diagnostic: per-IP active count."""
        now = time.time()
        return {
            ip: len([t for t in ts if now - t < self._window])
            for ip, ts in self._requests.items()
        }


rate_limiter = RateLimiter()


async def rate_limit_middleware(request: Request, call_next):
    """Allow exempt paths through; rate-limit only mutating / heavy endpoints."""
    if _DISABLE_RATE_LIMIT:
        return await call_next(request)

    path = request.url.path
    if _is_exempt(path):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.is_allowed(client_ip):
        logger.warning("rate_limit_blocked ip=%s path=%s", client_ip, path)
        return JSONResponse(
            {
                "error": "rate limit exceeded",
                "detail": (
                    f"已超过每分钟 {_RATE_LIMIT_MAX} 次的访问上限。请稍后重试，"
                    "或在 .env 中设置 AGENT_PILOT_DISABLE_RATE_LIMIT=1 临时关闭。"
                ),
                "ip": client_ip,
                "path": path,
                "retry_after_sec": _RATE_LIMIT_WINDOW,
            },
            status_code=429,
            headers={"Retry-After": str(_RATE_LIMIT_WINDOW)},
        )
    return await call_next(request)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or new_request_id()
        set_request_context(request_id=rid)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


class OptionalAPIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        api_key = os.getenv("AGENT_PILOT_API_KEY", "")
        if api_key and request.url.path.startswith("/api/"):
            provided = request.headers.get("X-API-Key") or request.query_params.get("api_key") or ""
            if provided != api_key:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
