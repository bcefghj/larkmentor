"""ContextPack — Agent 执行任务前的标准输入集合（PRD §7）.

PRD §7.4 字段:
  - task_goal: 任务目标
  - source_messages: 被引用的 IM 对话摘要
  - source_docs: 被引用的文档链接 + 摘要
  - user_added_materials: 执行人补充材料
  - output_requirements: 输出形式 / 页数 / 风格 / 受众 / 语言
  - constraints: 截止时间 / 保密 / 格式
  - owner: 当前阶段执行人
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from pilot.runtime.session import ArtifactRef

logger = logging.getLogger("pilot.context.pack")


@dataclass
class SourceMessage:
    sender_open_id: str
    text: str
    chat_id: str = ""
    msg_id: str = ""
    ts: int = 0


@dataclass
class SourceDoc:
    title: str
    url: str
    summary: str = ""
    permission: str = "ok"  # ok | denied | unknown


@dataclass
class OutputRequirements:
    primary: str = "doc"  # doc | slide | canvas | trio
    audience: str = ""    # leader | colleague | customer | self
    pages: int = 0
    language: str = "zh-CN"
    style: str = ""        # formal | casual | data-heavy
    must_include: list[str] = field(default_factory=list)


@dataclass
class Constraints:
    deadline_ts: int = 0
    confidential: bool = False
    format: str = ""


@dataclass
class ContextPack:
    pack_id: str = ""
    task_id: str = ""
    task_goal: str = ""
    source_messages: list[SourceMessage] = field(default_factory=list)
    source_docs: list[SourceDoc] = field(default_factory=list)
    user_added_materials: list[ArtifactRef] = field(default_factory=list)
    output_requirements: OutputRequirements = field(default_factory=OutputRequirements)
    constraints: Constraints = field(default_factory=Constraints)
    owner_open_id: str = ""

    confirmed: bool = False
    confirmed_ts: int = 0

    created_ts: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "task_id": self.task_id,
            "task_goal": self.task_goal,
            "source_messages": [asdict(m) for m in self.source_messages],
            "source_docs": [asdict(d) for d in self.source_docs],
            "user_added_materials": [asdict(a) for a in self.user_added_materials],
            "output_requirements": asdict(self.output_requirements),
            "constraints": asdict(self.constraints),
            "owner_open_id": self.owner_open_id,
            "confirmed": self.confirmed,
            "confirmed_ts": self.confirmed_ts,
            "created_ts": self.created_ts,
        }

    def render_summary(self) -> dict[str, Any]:
        """生成 PRD §7.2 上下文确认卡片的 summary 字段."""
        used: list[str] = []
        if self.source_messages:
            used.append(f"IM 对话 · {len(self.source_messages)} 条")
        if self.source_docs:
            used.append(f"文档 · {len(self.source_docs)} 份")
        if self.user_added_materials:
            used.append(f"补充材料 · {len(self.user_added_materials)} 个")

        missing: list[str] = []
        if not self.source_messages:
            missing.append("IM 对话上下文")
        if not self.source_docs:
            missing.append("关联文档")
        if self.output_requirements.primary in ("slide", "trio") and not self.output_requirements.pages:
            missing.append("PPT 页数")
        if not self.output_requirements.audience:
            missing.append("汇报对象")

        return {
            "task_goal": self.task_goal,
            "used": used,
            "missing": missing,
            "owner": self.owner_open_id,
            "primary_output": self.output_requirements.primary,
        }


# ── Builder ──


class ContextPackBuilder:
    """从 IM 历史 + 用户补充建出 ContextPack."""

    def __init__(self) -> None:
        self._counter = 0

    def build(
        self,
        *,
        task_id: str,
        task_goal: str,
        owner_open_id: str,
        im_messages: list[SourceMessage] | None = None,
        source_docs: list[SourceDoc] | None = None,
        user_added: list[ArtifactRef] | None = None,
        output_primary: str = "doc",
        output_audience: str = "",
        output_pages: int = 0,
        deadline_ts: int = 0,
    ) -> ContextPack:
        self._counter += 1
        return ContextPack(
            pack_id=f"cp_{int(time.time())}_{self._counter:04d}",
            task_id=task_id,
            task_goal=task_goal,
            source_messages=list(im_messages or []),
            source_docs=list(source_docs or []),
            user_added_materials=list(user_added or []),
            output_requirements=OutputRequirements(
                primary=output_primary,
                audience=output_audience,
                pages=output_pages,
            ),
            constraints=Constraints(deadline_ts=deadline_ts),
            owner_open_id=owner_open_id,
        )

    def confirm(self, pack: ContextPack) -> ContextPack:
        pack.confirmed = True
        pack.confirmed_ts = int(time.time())
        return pack
