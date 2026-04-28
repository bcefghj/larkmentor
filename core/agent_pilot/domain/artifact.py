"""Artifact · 任务产出物.

5 类产出（PRD §10 + §15.1）：
- DOC      飞书 Docx / 本地 markdown
- PPT      Slidev → pptx
- CANVAS   tldraw 场景 + 飞书画板
- SPEECH   演讲稿（PRD §15.2 加分项）
- ARCHIVE  归档包（PRD §F: manifest + 飞书 Docx 摘要）

每个 Artifact 持有：访问 URL / 本地路径 / 摘要 / 元数据。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class ArtifactKind(str, Enum):
    DOC = "doc"
    PPT = "ppt"
    CANVAS = "canvas"
    SPEECH = "speech"
    ARCHIVE = "archive"
    RECORDING = "recording"  # ASR 转写
    REFERENCE = "reference"  # citation references.md


@dataclass
class Artifact:
    artifact_id: str
    task_id: str
    kind: ArtifactKind
    title: str = ""
    summary: str = ""
    feishu_url: str = ""        # 飞书 Doc / Slide URL
    local_path: str = ""        # 本地 fallback 路径
    share_url: str = ""         # 公开分享链接
    file_size_bytes: int = 0
    page_count: int = 0
    word_count: int = 0
    created_ts: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


__all__ = ["Artifact", "ArtifactKind"]
