"""PromptAssembler — 装配 system prompt + messages.

关键设计（cache stability first）:
  - SYSTEM_PROMPT_DYNAMIC_BOUNDARY 之前的内容是 cache-friendly（全局可复用）
  - boundary 之后是 session-specific（每次都不同）
  - boundary 标记被 LLM provider 识别后可分段缓存
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from pilot.context.agents_md import load_cascade
from pilot.context.event_log import EventLog
from pilot.runtime.session import Session, Task

logger = logging.getLogger("pilot.context.prompt_assembler")

SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "<!-- SYSTEM_PROMPT_DYNAMIC_BOUNDARY -->"


CORE_PROLOGUE = """你是 Agent-Pilot V1，一个驻扎在飞书 IM 中的 AI 主驾驶。

## 你的身份
- 名字: Agent-Pilot
- 定位: 把"群聊讨论 → 文档 → 画布 → PPT + 演讲稿"压缩到 90 秒一键交付
- 同事: 戴尚好（开发）、李洁盈（产品）

## 你的工作方式
1. 在飞书 IM 中识别用户意图（三闸门：规则 → LLM → 最小信息）
2. 模糊时主动澄清，不擅自执行
3. 用三 Agent harness（Planner / Generator / Evaluator）执行长任务
4. 单线程写：所有"写"动作只能由 Writer 一个串行做（Cognition 教训）
5. 大段内容用 artifact:// handle 引用，不塞 conversation history
6. destructive tool 必须经 Governance 4 级权限

## 工具使用规则
- 优先用 Skill（如 lark-im / lark-doc / pilot-slide），其次用 raw 工具
- read 工具尽量并行，write 工具必须串行
- 工具调用前默念："这是 read 还是 write？需不需要用户确认？"

## 输出风格
- 中文为主
- 简洁、可执行、不啰嗦
- 用结构化卡片代替长文字
"""


class PromptAssembler:
    """把 5 个数据源装配成 system prompt + messages.

    数据源:
      1. CORE_PROLOGUE (cached, global)
      2. AGENTS.md cascade (cached per project)
      3. SYSTEM_PROMPT_DYNAMIC_BOUNDARY
      4. Session 元信息（chat_id, user, mode）
      5. Event log (append-only history)
    """

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        max_history_events: int = 30,
    ) -> None:
        self.repo_root = repo_root or Path(os.getcwd())
        self.max_history_events = max_history_events
        self._cached_agents_md: str | None = None

    async def assemble_system_prompt(self, session: Session) -> str:
        # cache：AGENTS.md cascade 整个 process 缓存一次
        if self._cached_agents_md is None:
            self._cached_agents_md = load_cascade(self.repo_root)

        # 静态前缀（global cache）
        static_part = (
            f"{CORE_PROLOGUE}\n\n"
            f"## 项目级 AGENTS.md cascade\n\n"
            f"{self._cached_agents_md or '(无)'}\n\n"
        )

        # 动态后缀（session-specific）
        dynamic_part = (
            f"{SYSTEM_PROMPT_DYNAMIC_BOUNDARY}\n\n"
            f"## 当前 Session\n\n"
            f"- session_id: {session.session_id}\n"
            f"- user: {session.user_open_id}\n"
            f"- chat_id: {session.chat_id}\n"
            f"- mode: {session.mode.value}\n"
            f"- model_profile: {session.model_profile}\n"
            f"- approval_mode: {session.approval_mode}\n"
        )

        return static_part + dynamic_part

    async def assemble_messages(self, session: Session, task: Task | None) -> list[dict[str, Any]]:
        """从 EventLog 中拼出 messages 数组."""
        log = EventLog(session.session_id)
        events = log.tail(self.max_history_events)

        messages: list[dict[str, Any]] = []
        if task and task.intent:
            messages.append({
                "role": "user",
                "content": f"[原始意图] {task.intent}",
            })

        for evt in events:
            kind = evt.get("kind", "")
            payload = evt.get("payload", {}) or {}
            if kind == "user_message":
                messages.append({"role": "user", "content": payload.get("text", "")})
            elif kind == "assistant_text":
                messages.append({"role": "assistant", "content": payload.get("text", "")})
            elif kind == "tool_result":
                # 用紧凑格式注入 tool result，避免 token 爆炸
                tool_name = payload.get("tool_name", "")
                content = payload.get("content", {})
                content_str = self._compact_tool_result(content)
                messages.append({
                    "role": "user",
                    "content": f"[tool:{tool_name}] {content_str}",
                })
            # 其他 kind 不进 messages（context_reset / step.done 等只用于审计）

        return messages

    @staticmethod
    def _compact_tool_result(content: Any, max_len: int = 800) -> str:
        if content is None:
            return "(empty)"
        if isinstance(content, str):
            return content[:max_len] + ("…" if len(content) > max_len else "")
        if isinstance(content, dict):
            keys = ", ".join(list(content.keys())[:8])
            return f"<dict keys={keys}>"
        if isinstance(content, list):
            return f"<list len={len(content)}>"
        return str(content)[:max_len]

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """简单 token 估算（按字符 / 4 估算英文 + 按字符估算中文）."""
        total = 0
        for m in messages:
            c = m.get("content", "")
            if isinstance(c, str):
                # 中文每字 ≈ 1.5 token，英文每 4 字 ≈ 1 token
                cjk = sum(1 for ch in c if "\u4e00" <= ch <= "\u9fff")
                non_cjk = len(c) - cjk
                total += int(cjk * 1.5 + non_cjk / 4)
            elif isinstance(c, list):
                total += 50  # 粗略
        return total

    async def append_event(self, session: Session, kind: str, payload: dict[str, Any]) -> None:
        log = EventLog(session.session_id)
        await log.append(kind, payload)
