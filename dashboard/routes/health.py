"""Health check and version endpoints."""

from __future__ import annotations

import sys
import time

from fastapi import APIRouter

from config import Config

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Kubernetes-style liveness probe."""
    return {"status": "ok", "version": Config.VERSION, "timestamp": time.time()}


@router.get("/ready")
async def readiness_check():
    """Kubernetes-style readiness probe - checks dependencies."""
    checks = {
        "llm_configured": bool(Config.ARK_API_KEY or getattr(Config, "MIMO_API_KEY", "")),
        "feishu_configured": bool(Config.FEISHU_APP_ID),
    }
    all_ready = all(checks.values())
    return {"ready": all_ready, "checks": checks}


@router.get("/api/health")
async def health_legacy():
    """Legacy health endpoint (backward compat)."""
    from dashboard.server import DEMO_MODE
    return {"status": "ok", "version": Config.VERSION, "mode": "demo" if DEMO_MODE else "live"}


@router.get("/api/v1/version")
async def get_version():
    return {
        "version": Config.VERSION,
        "name": "Agent-Pilot",
        "python": sys.version,
        "features": [
            "orchestrator_v2", "mcp", "crdt", "function_calling",
            "harness_v2", "lark_cli_skills", "exec_trace", "streaming",
        ],
    }
