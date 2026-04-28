"""Agent Teams (Claude Code 2026 实验特性) · Redis pub/sub 多 agent 在线协作。

与 subagent silo 不同，teams 允许：
- 多 agent 持续在线（不 kill）
- 共享一个 task list（data/tasks/{team_id}/task_list.md）
- Agent-to-agent 消息（通过 Redis pub/sub）
- 架构决策辩论

Fallback 到本地内存 pub/sub（无 Redis 时）。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("agent.teams")


@dataclass
class TeamMessage:
    team_id: str
    from_agent: str
    to_agent: str  # "*" for broadcast
    kind: str  # "propose" / "critique" / "agree" / "question" / "decision"
    content: str
    ts: float = field(default_factory=time.time)


@dataclass
class TeamTask:
    task_id: str
    title: str
    owner: str = ""
    status: str = "pending"  # pending/in_progress/done
    updated_at: float = field(default_factory=time.time)


class InMemoryBus:
    """Local fallback for Redis pub/sub."""
    def __init__(self) -> None:
        self.channels: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def publish(self, channel: str, msg: Dict) -> None:
        with self._lock:
            self.channels[channel].append(msg)
            for cb in self.subscribers[channel]:
                try:
                    cb(msg)
                except Exception:
                    pass

    def subscribe(self, channel: str, callback: Callable) -> None:
        with self._lock:
            self.subscribers[channel].append(callback)

    def replay(self, channel: str, n: int = 20) -> List[Dict]:
        with self._lock:
            return list(self.channels[channel])[-n:]


class AgentTeam:
    """3-5 agent 持续在线，共享 task list + 消息总线。"""

    def __init__(self, team_id: str, agents: List[str], *, use_redis: bool = False) -> None:
        self.team_id = team_id
        self.agents = agents
        self.tasks_dir = Path.cwd() / "data" / "teams" / team_id
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.task_list_path = self.tasks_dir / "task_list.md"
        self.message_log_path = self.tasks_dir / "messages.jsonl"
        if use_redis:
            try:
                import redis  # type: ignore
                self.redis = redis.Redis(host="localhost", port=6379, decode_responses=True)
                self.redis.ping()
                self._bus_type = "redis"
            except Exception as e:
                logger.debug("redis unavailable, fallback to in-memory: %s", e)
                self.bus = InMemoryBus()
                self._bus_type = "memory"
        else:
            self.bus = InMemoryBus()
            self._bus_type = "memory"

    def channel(self) -> str:
        return f"team:{self.team_id}"

    def send(self, msg: TeamMessage) -> None:
        data = {
            "team_id": msg.team_id, "from_agent": msg.from_agent,
            "to_agent": msg.to_agent, "kind": msg.kind,
            "content": msg.content, "ts": msg.ts,
        }
        if self._bus_type == "redis":
            self.redis.publish(self.channel(), json.dumps(data))
        else:
            self.bus.publish(self.channel(), data)
        # Also persist to log
        try:
            with self.message_log_path.open("a") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def recent_messages(self, n: int = 20) -> List[Dict]:
        if self._bus_type == "memory":
            return self.bus.replay(self.channel(), n=n)
        # Redis
        try:
            # Redis pub/sub is ephemeral; read from log
            if self.message_log_path.exists():
                lines = self.message_log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                return [json.loads(l) for l in lines[-n:]]
        except Exception:
            pass
        return []

    def task_list(self) -> List[Dict[str, Any]]:
        """Simple flat markdown task list: `- [ ] title (owner)`."""
        if not self.task_list_path.exists():
            return []
        tasks = []
        for line in self.task_list_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("- ["):
                continue
            done = "[x]" in line.lower()
            title = line.split("]", 1)[1].strip() if "]" in line else line
            tasks.append({"done": done, "title": title})
        return tasks

    def add_task(self, title: str, owner: str = "") -> None:
        line = f"- [ ] {title}"
        if owner:
            line += f" @{owner}"
        with self.task_list_path.open("a") as f:
            f.write(line + "\n")

    def snapshot(self) -> Dict[str, Any]:
        return {
            "team_id": self.team_id,
            "agents": self.agents,
            "bus": self._bus_type,
            "recent_messages": self.recent_messages(10),
            "tasks": self.task_list(),
        }


# ── public helpers ──


def architect_debate(topic: str, *, team_id: str = "", providers=None) -> Dict[str, Any]:
    """Demo: 3 agent 对架构决策辩论 3 轮后共识。"""
    team_id = team_id or f"debate-{uuid.uuid4().hex[:6]}"
    team = AgentTeam(team_id, agents=["pilot", "debater", "researcher"])
    from .providers import default_providers
    providers = providers or default_providers()

    # Round 1: each agent proposes
    for role in ["pilot", "debater", "researcher"]:
        task_kind = {"pilot": "reasoning", "debater": "chinese_chat", "researcher": "long_context"}[role]
        persona = {
            "pilot": "你是一个务实的项目经理，优先考虑快速落地。",
            "debater": "你是一个批判性辩论者，找出方案中的潜在问题。",
            "researcher": "你是一个深度研究员，提供数据支撑。",
        }[role]
        prompt = f"{persona}\n\n话题：{topic}\n\n请用 300 字以内给出你的观点。"
        text = providers.chat([{"role": "user", "content": prompt}], task_kind=task_kind, max_tokens=600)
        team.send(TeamMessage(team_id=team_id, from_agent=role, to_agent="*", kind="propose", content=text))

    # Round 2: cross-critique
    messages = team.recent_messages(10)
    critiques = []
    for role in ["pilot", "debater", "researcher"]:
        others = [m["content"][:400] for m in messages if m["from_agent"] != role]
        prompt = (
            f"你是 {role}。其他两个观点：\n\n" + "\n---\n".join(others) +
            f"\n\n对这些观点做出批判（200 字以内）："
        )
        task_kind = {"pilot": "reasoning", "debater": "chinese_chat", "researcher": "long_context"}[role]
        text = providers.chat([{"role": "user", "content": prompt}], task_kind=task_kind, max_tokens=400)
        team.send(TeamMessage(team_id=team_id, from_agent=role, to_agent="*", kind="critique", content=text))
        critiques.append((role, text))

    # Round 3: converge
    summary_prompt = (
        f"话题：{topic}\n\n"
        f"3 轮辩论的所有观点：\n" + "\n---\n".join(m["content"][:300] for m in team.recent_messages(20)) +
        f"\n\n请综合所有观点，给出最终决策建议（含关键依据和取舍）。"
    )
    final = providers.chat([{"role": "user", "content": summary_prompt}], task_kind="reasoning", max_tokens=1200)
    team.send(TeamMessage(team_id=team_id, from_agent="orchestrator", to_agent="*", kind="decision", content=final))

    return {
        "team_id": team_id,
        "rounds": 3,
        "final_decision": final,
        "messages": team.recent_messages(30),
        "snapshot": team.snapshot(),
    }
