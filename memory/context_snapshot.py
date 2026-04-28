"""Work context snapshot for Context Recall."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ContextSnapshot:
    """Captures user work context at focus-start time."""
    user_open_id: str
    calendar_events: List[str] = field(default_factory=list)
    active_tasks: List[str] = field(default_factory=list)
    last_user_message: str = ""
    custom_context: str = ""

    def summary(self) -> str:
        parts = []
        if self.calendar_events:
            parts.append("日程: " + "; ".join(self.calendar_events))
        if self.active_tasks:
            parts.append("任务: " + "; ".join(self.active_tasks))
        if self.custom_context:
            parts.append("备注: " + self.custom_context)
        if self.last_user_message:
            parts.append("最后消息: " + self.last_user_message[:100])
        return "\n".join(parts) if parts else "无额外上下文"


_snapshots: Dict[str, ContextSnapshot] = {}


def save_snapshot(snap: ContextSnapshot):
    _snapshots[snap.user_open_id] = snap


def get_snapshot(user_open_id: str) -> Optional[ContextSnapshot]:
    return _snapshots.get(user_open_id)


def clear_snapshot(user_open_id: str):
    _snapshots.pop(user_open_id, None)
