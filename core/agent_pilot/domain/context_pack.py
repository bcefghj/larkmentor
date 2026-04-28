"""ContextPack · PRD §7.4 标准上下文契约.

输入到 Pilot 主流程的所有信息都打包成一个 ``ContextPack``——
无论资料来自 IM 群聊摘要、飞书 Wiki、用户上传文件还是粘贴链接。

PRD §7.4 字段（与本实现 1:1 对应）：

| PRD field            | dataclass attr                |
|----------------------|-------------------------------|
| task_goal            | task_goal                     |
| source_messages      | source_messages               |
| source_docs          | source_docs                   |
| user_added_materials | user_added_materials          |
| output_requirements  | output_requirements           |
| constraints          | constraints                   |
| owner                | owner_open_id                 |

Q4 已结论：**三档资料源**——粘贴链接 / 上传文件 / 飞书 Wiki+Docx 真实 API。
本模型用 ``MaterialKind`` 标 source，下游 ``application.context_service``
负责具体抓取/校验。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MaterialKind(str, Enum):
    """三档资料源（Q4）。"""

    LINK = "link"               # 粘贴链接（开放 web）
    UPLOAD = "upload"           # 用户上传的文件
    FEISHU_DOC = "feishu_doc"   # 飞书 Docx（真实 API）
    FEISHU_WIKI = "feishu_wiki" # 飞书 Wiki（真实 API）
    FEISHU_BITABLE = "feishu_bitable"  # 飞书多维表格
    BITABLE_ROW = "bitable_row"  # 飞书 Bitable Agent Node（PRD 加分项）
    IM_THREAD = "im_thread"     # IM 群聊上下文片段
    HISTORY_TASK = "history_task"  # 历史归档任务（FlowMemory archival）


@dataclass
class SourceMessage:
    """一条 IM 消息片段."""

    sender_open_id: str
    text: str
    ts: int = 0
    chat_id: str = ""
    msg_id: str = ""

    def to_summary(self, max_chars: int = 80) -> str:
        body = self.text.replace("\n", " ")[:max_chars]
        return f"[{self.sender_open_id[-4:] or '??'}] {body}"


@dataclass
class SourceDoc:
    """飞书 Wiki / Docx / 上传文件的引用."""

    kind: MaterialKind
    title: str = ""
    url: str = ""               # 飞书 Doc URL or external link
    doc_token: str = ""         # 飞书 doc_token（如适用）
    summary: str = ""           # 一两句话摘要
    excerpt: str = ""           # 关键正文片段
    permission_ok: bool = True  # 用户是否有读权限
    fetched_ts: int = 0


@dataclass
class UserMaterial:
    """执行人补充资料（上传/粘贴/手输）."""

    kind: MaterialKind
    title: str = ""
    body: str = ""              # 文本内容（如手输说明）
    url: str = ""               # 链接资料
    file_path: str = ""         # 上传文件本地路径（沙箱内）
    note: str = ""              # 用户备注


@dataclass
class OutputRequirements:
    """PRD §7.4 ``output_requirements``."""

    primary: str = "doc"        # "doc" / "ppt" / "canvas" / "doc+ppt"
    pages: int = 0              # 0 = 不限
    style: str = ""             # "boss_report" / "internal" / "casual" / "academic"
    audience: str = ""          # "leader" / "team" / "client"
    language: str = "zh-CN"
    tone: str = ""              # "formal" / "neutral" / "warm"
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Constraints:
    """PRD §7.4 ``constraints``."""

    deadline_ts: int = 0        # 0 = 无 deadline
    confidential: bool = False
    format: str = ""            # "pdf" / "pptx" / "feishu_doc"
    must_cite: bool = True      # claim 必须有 source（启用 Citation Agent）
    must_validate: bool = True  # 必须经过 @validator 审查
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextPack:
    """PRD §7.4 标准上下文契约·完整版.

    Application 层 ``context_service.build_context_pack(task)`` 产出。
    Planner / Orchestrator 必须以它为唯一输入，不能直接读 IM 原文。
    """

    task_id: str
    task_goal: str
    owner_open_id: str
    source_messages: List[SourceMessage] = field(default_factory=list)
    source_docs: List[SourceDoc] = field(default_factory=list)
    user_added_materials: List[UserMaterial] = field(default_factory=list)
    output_requirements: OutputRequirements = field(default_factory=OutputRequirements)
    constraints: Constraints = field(default_factory=Constraints)
    # ── 元数据 ──
    pack_id: str = ""
    created_ts: int = 0
    confirmed_by_owner: bool = False  # PRD §7.3 用户确认
    confirm_ts: int = 0

    # ── helpers ──
    def total_chars(self) -> int:
        n = sum(len(m.text) for m in self.source_messages)
        n += sum(len(d.excerpt or d.summary) for d in self.source_docs)
        n += sum(len(m.body or m.note) for m in self.user_added_materials)
        return n

    def is_confirmed(self) -> bool:
        return self.confirmed_by_owner

    def missing(self) -> List[str]:
        """返回缺失的关键要素 (PRD §7.2 「建议补充资料」)."""
        gaps: List[str] = []
        if not self.task_goal.strip():
            gaps.append("task_goal")
        if not self.source_messages and not self.source_docs and not self.user_added_materials:
            gaps.append("any_material")
        if not self.output_requirements.primary:
            gaps.append("output_format")
        if self.output_requirements.audience == "" and self.output_requirements.style == "":
            gaps.append("audience_or_style")
        return gaps

    def has_min_info(self) -> bool:
        """PRD §5 闸门 3 「最小可执行信息」校验.

        最小集合：(task_goal) AND (至少一种资料源) AND (output_requirements.primary)
        """
        return (
            bool(self.task_goal.strip())
            and bool(self.output_requirements.primary)
            and (
                bool(self.source_messages)
                or bool(self.source_docs)
                or bool(self.user_added_materials)
            )
        )


__all__ = [
    "MaterialKind",
    "SourceMessage",
    "SourceDoc",
    "UserMaterial",
    "OutputRequirements",
    "Constraints",
    "ContextPack",
]
