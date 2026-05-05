"""Dashboard middleware – extracted from server.py for separation of concerns."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Dict, List

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from core.structured_logging import new_request_id, set_request_context


class RateLimiter:
    """Simple in-memory sliding-window rate limiter."""

    def __init__(self, max_requests: int = 60, window_sec: int = 60):
        self._max = max_requests
        self._window = window_sec
        self._requests: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(self, client_ip: str) -> bool:
        now = time.time()
        reqs = self._requests[client_ip]
        reqs[:] = [t for t in reqs if now - t < self._window]
        if len(reqs) >= self._max:
            return False
        reqs.append(now)
        return True


rate_limiter = RateLimiter()


async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.is_allowed(client_ip):
        return JSONResponse({"error": "rate limit exceeded"}, status_code=429)
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
