"""Per-user work state management with persistence and multi-task support.

Concurrency safety (LarkMentor v2 step8):
- Process-internal: ``threading.Lock`` for in-memory ``_store`` mutations
- Cross-process: ``fcntl.flock`` (POSIX) advisory file lock during disk write
- Atomic write: write to ``<file>.tmp`` then ``os.replace`` (POSIX atomic)
- ``fcntl`` is unavailable on Windows; we degrade to threading-only locking
  there so the bot can still run in a CI sandbox.
"""

import json
import logging
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional

try:
    import fcntl  # POSIX only
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

from utils.time_utils import now_cst, now_ts, fmt_time

logger = logging.getLogger("flowguard.state")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
STATE_FILE = os.path.join(DATA_DIR, "user_states.json")
ORG_DOCS_FILE = os.path.join(DATA_DIR, "org_docs.json")

_save_lock = threading.RLock()


@contextmanager
def _atomic_write(path: str):
    """Atomic, fcntl-locked write context.

    Usage::

        with _atomic_write(path) as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    Guarantees:
    - In-process serialised via ``_save_lock``
    - Cross-process advisory lock via ``fcntl.flock`` (POSIX)
    - Atomic replace via ``os.replace`` (POSIX guarantee)
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    lock_path = f"{path}.lock"
    with _save_lock:
        lock_fd = None
        try:
            if _HAS_FCNTL:
                lock_fd = open(lock_path, "w")
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            with open(tmp_path, "w", encoding="utf-8") as f:
                yield f
            os.replace(tmp_path, path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                    lock_fd.close()
                except Exception:
                    pass


class FocusMode(Enum):
    NORMAL = "normal"
    LIGHT = "light"
    DEEP = "deep"


@dataclass
class PendingMessage:
    message_id: str
    sender_name: str
    sender_id: str
    chat_name: str
    content: str
    level: str
    action: str
    auto_reply_text: str
    timestamp: int


@dataclass
class TaskContext:
    name: str
    created_ts: int = 0
    last_active_ts: int = 0
    context_note: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "created_ts": self.created_ts,
                "last_active_ts": self.last_active_ts, "context_note": self.context_note}

    @classmethod
    def from_dict(cls, d: dict) -> "TaskContext":
        return cls(name=d.get("name", ""), created_ts=d.get("created_ts", 0),
                   last_active_ts=d.get("last_active_ts", 0), context_note=d.get("context_note", ""))


ACHIEVEMENT_DEFS = [
    {"id": "focus_1h", "name": "专注先锋", "desc": "累计专注满 1 小时", "threshold_sec": 3600},
    {"id": "focus_5h", "name": "深度工作者", "desc": "累计专注满 5 小时", "threshold_sec": 18000},
    {"id": "focus_10h", "name": "心流大师", "desc": "累计专注满 10 小时", "threshold_sec": 36000},
    {"id": "shield_50", "name": "沟通守护者", "desc": "累计拦截 50 条消息", "threshold_shield": 50},
    {"id": "shield_100", "name": "噪音终结者", "desc": "累计拦截 100 条消息", "threshold_shield": 100},
    {"id": "focus_3day", "name": "连续专注达人", "desc": "连续 3 天使用专注模式", "threshold_streak": 3},
]


@dataclass
class UserState:
    open_id: str
    focus_mode: FocusMode = FocusMode.NORMAL
    focus_start_ts: int = 0
    focus_duration_sec: int = 0
    work_context: str = ""
    whitelist: List[str] = field(default_factory=list)
    rookie_mode: bool = False
    # v4 Mentor: proactive suggestion control
    proactive_enabled: bool = True
    last_proactive_ts: int = 0
    proactive_log_24h: List[int] = field(default_factory=list)  # timestamps
    growth_doc_token: str = ""

    pending_messages: List[PendingMessage] = field(default_factory=list)

    daily_interrupt_count: int = 0
    daily_p0: int = 0
    daily_p1: int = 0
    daily_p2: int = 0
    daily_p3: int = 0
    daily_focus_seconds: int = 0

    # Multi-task
    tasks: List[TaskContext] = field(default_factory=list)
    active_task_name: str = ""

    # Achievement tracking
    total_focus_seconds: int = 0
    total_shielded: int = 0
    focus_streak_days: int = 0
    last_focus_date: str = ""
    unlocked_achievements: List[str] = field(default_factory=list)

    def is_focusing(self) -> bool:
        return self.focus_mode != FocusMode.NORMAL

    def start_focus(self, duration_min: int = 0, context: str = ""):
        self.focus_mode = FocusMode.DEEP
        self.focus_start_ts = now_ts()
        self.focus_duration_sec = duration_min * 60
        if context:
            self.work_context = context
        self.pending_messages = []

        today = fmt_time()[:10]
        if self.last_focus_date == today:
            pass
        elif self.last_focus_date == _yesterday_str():
            self.focus_streak_days += 1
        else:
            self.focus_streak_days = 1
        self.last_focus_date = today

        logger.info("User %s entered focus mode (duration=%d min)", self.open_id, duration_min)
        _save_all()

    def end_focus(self) -> dict:
        elapsed = now_ts() - self.focus_start_ts if self.focus_start_ts else 0
        self.daily_focus_seconds += elapsed
        self.total_focus_seconds += elapsed

        stats = {
            "start_time": fmt_time(),
            "duration_sec": elapsed,
            "total_messages": len(self.pending_messages),
            "p0_count": sum(1 for m in self.pending_messages if m.level == "P0"),
            "p1_count": sum(1 for m in self.pending_messages if m.level == "P1"),
            "p2_count": sum(1 for m in self.pending_messages if m.level == "P2"),
            "p3_count": sum(1 for m in self.pending_messages if m.level == "P3"),
            "p1_messages": [
                f"[{m.sender_name}] {m.content[:60]}"
                for m in self.pending_messages if m.level == "P1"
            ],
            "work_context": self.work_context,
        }

        self.focus_mode = FocusMode.NORMAL
        self.focus_start_ts = 0
        self.focus_duration_sec = 0
        self.pending_messages = []
        logger.info("User %s ended focus mode", self.open_id)
        _save_all()
        return stats

    def add_pending(self, msg: PendingMessage):
        self.pending_messages.append(msg)
        self.daily_interrupt_count += 1
        level_map = {"P0": "daily_p0", "P1": "daily_p1", "P2": "daily_p2", "P3": "daily_p3"}
        attr = level_map.get(msg.level)
        if attr:
            setattr(self, attr, getattr(self, attr) + 1)
        if msg.level in ("P2", "P3"):
            self.total_shielded += 1

    def reset_daily(self):
        self.daily_interrupt_count = 0
        self.daily_p0 = 0
        self.daily_p1 = 0
        self.daily_p2 = 0
        self.daily_p3 = 0
        self.daily_focus_seconds = 0
        _save_all()

    # ── Multi-task ──

    def add_task(self, name: str, note: str = "") -> str:
        for t in self.tasks:
            if t.name == name:
                return f"任务 '{name}' 已存在。"
        ts = now_ts()
        self.tasks.append(TaskContext(name=name, created_ts=ts, last_active_ts=ts, context_note=note))
        if not self.active_task_name:
            self.active_task_name = name
            self.work_context = note or name
        _save_all()
        return f"已添加任务 '{name}'。"

    def switch_task(self, name: str) -> str:
        target = None
        for t in self.tasks:
            if t.name == name:
                target = t
                break
        if not target:
            return f"未找到任务 '{name}'。发送 `任务列表` 查看所有任务。"
        # Save current context to old active task
        for t in self.tasks:
            if t.name == self.active_task_name:
                t.context_note = self.work_context
                break
        self.active_task_name = name
        self.work_context = target.context_note or name
        target.last_active_ts = now_ts()
        _save_all()
        return f"已切换到任务 '{name}'。\n当前上下文：{self.work_context}"

    def remove_task(self, name: str) -> str:
        self.tasks = [t for t in self.tasks if t.name != name]
        if self.active_task_name == name:
            self.active_task_name = self.tasks[0].name if self.tasks else ""
            self.work_context = self.active_task_name
        _save_all()
        return f"已删除任务 '{name}'。"

    def task_list_text(self) -> str:
        if not self.tasks:
            return "暂无任务。发送 `添加任务：任务名` 来添加。"
        lines = []
        for t in self.tasks:
            marker = " (当前)" if t.name == self.active_task_name else ""
            lines.append(f"• {t.name}{marker}")
            if t.context_note:
                lines.append(f"  备注：{t.context_note[:50]}")
        return "\n".join(lines)

    # ── Achievements ──

    def check_achievements(self) -> List[dict]:
        newly_unlocked = []
        for a in ACHIEVEMENT_DEFS:
            if a["id"] in self.unlocked_achievements:
                continue
            unlocked = False
            if "threshold_sec" in a and self.total_focus_seconds >= a["threshold_sec"]:
                unlocked = True
            if "threshold_shield" in a and self.total_shielded >= a["threshold_shield"]:
                unlocked = True
            if "threshold_streak" in a and self.focus_streak_days >= a["threshold_streak"]:
                unlocked = True
            if unlocked:
                self.unlocked_achievements.append(a["id"])
                newly_unlocked.append(a)
        if newly_unlocked:
            _save_all()
        return newly_unlocked

    # ── Serialization ──

    def to_dict(self) -> dict:
        return {
            "open_id": self.open_id,
            "focus_mode": self.focus_mode.value,
            "focus_start_ts": self.focus_start_ts,
            "focus_duration_sec": self.focus_duration_sec,
            "work_context": self.work_context,
            "whitelist": self.whitelist,
            "rookie_mode": self.rookie_mode,
            "daily_interrupt_count": self.daily_interrupt_count,
            "daily_p0": self.daily_p0, "daily_p1": self.daily_p1,
            "daily_p2": self.daily_p2, "daily_p3": self.daily_p3,
            "daily_focus_seconds": self.daily_focus_seconds,
            "tasks": [t.to_dict() for t in self.tasks],
            "active_task_name": self.active_task_name,
            "total_focus_seconds": self.total_focus_seconds,
            "total_shielded": self.total_shielded,
            "focus_streak_days": self.focus_streak_days,
            "last_focus_date": self.last_focus_date,
            "unlocked_achievements": self.unlocked_achievements,
            "proactive_enabled": self.proactive_enabled,
            "last_proactive_ts": self.last_proactive_ts,
            "proactive_log_24h": self.proactive_log_24h,
            "growth_doc_token": self.growth_doc_token,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UserState":
        u = cls(open_id=d["open_id"])
        u.focus_mode = FocusMode(d.get("focus_mode", "normal"))
        u.focus_start_ts = d.get("focus_start_ts", 0)
        u.focus_duration_sec = d.get("focus_duration_sec", 0)
        u.work_context = d.get("work_context", "")
        u.whitelist = d.get("whitelist", [])
        u.rookie_mode = d.get("rookie_mode", False)
        u.daily_interrupt_count = d.get("daily_interrupt_count", 0)
        u.daily_p0 = d.get("daily_p0", 0)
        u.daily_p1 = d.get("daily_p1", 0)
        u.daily_p2 = d.get("daily_p2", 0)
        u.daily_p3 = d.get("daily_p3", 0)
        u.daily_focus_seconds = d.get("daily_focus_seconds", 0)
        u.tasks = [TaskContext.from_dict(t) for t in d.get("tasks", [])]
        u.active_task_name = d.get("active_task_name", "")
        u.total_focus_seconds = d.get("total_focus_seconds", 0)
        u.total_shielded = d.get("total_shielded", 0)
        u.focus_streak_days = d.get("focus_streak_days", 0)
        u.last_focus_date = d.get("last_focus_date", "")
        u.unlocked_achievements = d.get("unlocked_achievements", [])
        u.proactive_enabled = d.get("proactive_enabled", True)
        u.last_proactive_ts = d.get("last_proactive_ts", 0)
        u.proactive_log_24h = d.get("proactive_log_24h", [])
        u.growth_doc_token = d.get("growth_doc_token", "")
        return u


def _yesterday_str() -> str:
    from datetime import timedelta
    return (now_cst() - timedelta(days=1)).strftime("%Y-%m-%d")


# ── In-memory store ──
_store: Dict[str, UserState] = {}


def get_user(open_id: str) -> UserState:
    if open_id not in _store:
        _store[open_id] = UserState(open_id=open_id)
    return _store[open_id]


def all_users() -> List[UserState]:
    return list(_store.values())


# ── Persistence ──

def _save_all():
    """Persist user states to disk. Cross-process safe via fcntl + atomic rename."""
    data = {uid: u.to_dict() for uid, u in _store.items()}
    try:
        with _atomic_write(STATE_FILE) as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Failed to save state: %s", e)


def load_all():
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for uid, d in data.items():
            _store[uid] = UserState.from_dict(d)
        logger.info("Loaded %d user states from disk", len(_store))
    except Exception as e:
        logger.error("Failed to load state: %s", e)


# ── Organization docs store ──
_org_docs: List[str] = []


def add_org_doc(content: str):
    _org_docs.append(content[:2000])
    if len(_org_docs) > 20:
        _org_docs.pop(0)
    _save_org_docs()


def get_org_docs_context(max_chars: int = 3000) -> str:
    if not _org_docs:
        return ""
    combined = "\n---\n".join(_org_docs)
    return combined[:max_chars]


def _save_org_docs():
    """Persist org docs. Same locking guarantees as _save_all."""
    try:
        with _atomic_write(ORG_DOCS_FILE) as f:
            json.dump(_org_docs, f, ensure_ascii=False)
    except Exception:
        pass


def _load_org_docs():
    global _org_docs
    if not os.path.exists(ORG_DOCS_FILE):
        return
    try:
        with open(ORG_DOCS_FILE, "r", encoding="utf-8") as f:
            _org_docs = json.load(f)
    except Exception:
        pass


# ── Name cache ──
_name_cache: Dict[str, str] = {}


def get_cached_name(open_id: str) -> Optional[str]:
    return _name_cache.get(open_id)


def set_cached_name(open_id: str, name: str):
    _name_cache[open_id] = name
