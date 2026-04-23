"""Human-in-the-Loop Approval · Shannon 启发

敏感工具（drive.delete / bitable.clear / im.batch_send / approval.reject）：
1. Agent 发起调用 → permissions.py 判定需要审批
2. cardkit.v1 发审批卡到用户（Approve / Deny / Always Allow）
3. 用户点按钮 → Webhook 回传 → Agent 继续或终止
4. "Always Allow" 写入 ~/.larkmentor/approvals.json，下次跳过
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent.approval")


@dataclass
class PendingApproval:
    token: str
    tool: str
    arguments: Dict[str, Any]
    plan_id: str = ""
    user_open_id: str = ""
    reason: str = ""
    created_at: float = field(default_factory=time.time)
    resolved: Optional[str] = None  # "approve" / "deny" / "always_allow"
    resolved_at: Optional[float] = None


class ApprovalManager:
    def __init__(self) -> None:
        self.home = Path(os.getenv("LARKMENTOR_HOME", str(Path.home() / ".larkmentor")))
        self.home.mkdir(parents=True, exist_ok=True)
        self.approvals_path = self.home / "approvals.json"
        self.pending: Dict[str, PendingApproval] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.approvals_path.exists():
            return
        try:
            data = json.loads(self.approvals_path.read_text())
            # `data` is {tool_name: True/False} for always_allow persisted
        except Exception as e:
            logger.debug("approvals load failed: %s", e)

    def request(
        self, tool: str, arguments: Dict[str, Any], *,
        plan_id: str = "", user_open_id: str = "",
        reason: str = "",
    ) -> PendingApproval:
        token = uuid.uuid4().hex[:16]
        p = PendingApproval(
            token=token, tool=tool, arguments=arguments,
            plan_id=plan_id, user_open_id=user_open_id, reason=reason,
        )
        with self._lock:
            self.pending[token] = p
        logger.info("approval requested: %s for %s", token, tool)
        return p

    def resolve(self, token: str, action: str) -> bool:
        if action not in ("approve", "deny", "always_allow"):
            return False
        with self._lock:
            p = self.pending.get(token)
            if not p:
                return False
            p.resolved = action
            p.resolved_at = time.time()

        if action == "always_allow":
            try:
                from .permissions import default_permission_gate
                default_permission_gate().register_always_allow(p.tool)
            except Exception as e:
                logger.warning("always_allow persist failed: %s", e)

        logger.info("approval resolved: %s → %s", token, action)
        return True

    def wait(self, token: str, *, timeout: float = 300.0) -> Optional[str]:
        """Poll pending[token].resolved until timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                p = self.pending.get(token)
                if not p:
                    return None
                if p.resolved:
                    return p.resolved
            time.sleep(0.5)
        return None

    def list_pending(self) -> List[PendingApproval]:
        with self._lock:
            return [p for p in self.pending.values() if not p.resolved]

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "pending_count": sum(1 for p in self.pending.values() if not p.resolved),
                "resolved_count": sum(1 for p in self.pending.values() if p.resolved),
                "recent": [
                    {"token": p.token, "tool": p.tool, "resolved": p.resolved}
                    for p in list(self.pending.values())[-10:]
                ],
            }


_singleton: Optional[ApprovalManager] = None


def default_approval_manager() -> ApprovalManager:
    global _singleton
    if _singleton is None:
        _singleton = ApprovalManager()
    return _singleton
