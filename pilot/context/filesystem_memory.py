"""文件系统作为 working memory（Modern Agent Harness Blueprint 2026 第 3 铁律）.

大段内容（7000 字 markdown / .pptx 文件 / 图片）一律落盘，conversation 中只放
ArtifactRef handle，避免上下文爆炸。

URI scheme:
  - artifact://reports/<session_id>/<artifact_id>.json     → DATA_DIR/artifacts/...
  - https://feishu.cn/docx/...                             → 飞书 Docx 直接 URL
  - file:///opt/agent-pilot/data/.../slide_xxx.pptx        → 本地文件路径
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from pilot.runtime.session import Artifact, ArtifactRef

logger = logging.getLogger("pilot.context.filesystem_memory")

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data"))).resolve()
ARTIFACTS_DIR = DATA_DIR / "artifacts"


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class FilesystemMemory:
    """Working memory store — artifact 增删查改 + URI 解析."""

    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id
        self.session_dir = _ensure(ARTIFACTS_DIR / (session_id or "_global"))

    def store_text(
        self,
        content: str,
        *,
        kind: str = "report",
        mime_type: str = "text/markdown",
        summary: str = "",
        tool: str = "",
        step_id: str = "",
    ) -> Artifact:
        """把文本/markdown 落盘，返回 Artifact handle."""
        aid = f"artifact_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        d = _ensure(self.session_dir / kind)
        ext = ".md" if mime_type.startswith("text/markdown") else ".txt"
        f = d / f"{aid}{ext}"
        f.write_text(content, encoding="utf-8")
        uri = f"artifact://{self.session_id or '_global'}/{kind}/{aid}{ext}"
        return Artifact(
            artifact_id=aid,
            uri=uri,
            mime_type=mime_type,
            summary=summary or content[:120],
            sha256=_sha256_str(content),
            source={"tool": tool, "session_id": self.session_id, "step_id": step_id},
            size_bytes=len(content.encode("utf-8")),
        )

    def store_json(
        self,
        data: dict[str, Any] | list[Any],
        *,
        kind: str = "data",
        summary: str = "",
        tool: str = "",
        step_id: str = "",
    ) -> Artifact:
        s = json.dumps(data, ensure_ascii=False, indent=2)
        return self.store_text(
            s,
            kind=kind,
            mime_type="application/json",
            summary=summary,
            tool=tool,
            step_id=step_id,
        )

    def store_external(
        self,
        url: str,
        *,
        mime_type: str = "text/uri-list",
        summary: str = "",
        tool: str = "",
        step_id: str = "",
    ) -> Artifact:
        """注册一个外部资源（飞书 Docx URL / Drive URL）."""
        return Artifact(
            artifact_id=f"artifact_{int(time.time())}_{uuid.uuid4().hex[:6]}",
            uri=url,
            mime_type=mime_type,
            summary=summary or url[:120],
            sha256=_sha256_str(url),
            source={"tool": tool, "session_id": self.session_id, "step_id": step_id},
            size_bytes=0,
        )

    def resolve(self, uri: str) -> str:
        """从 artifact:// URI 读出文本内容（external URL 不读，只返回 URI）."""
        if not uri:
            return ""
        if uri.startswith("artifact://"):
            rest = uri[len("artifact://"):]
            f = ARTIFACTS_DIR / rest
            if f.exists():
                try:
                    return f.read_text(encoding="utf-8")
                except Exception as e:
                    logger.warning("resolve artifact failed: %s", e)
                    return ""
            return ""
        if uri.startswith("file://"):
            f = Path(uri[len("file://"):])
            if f.exists() and f.is_file():
                try:
                    return f.read_text(encoding="utf-8")
                except Exception:
                    return ""
        return ""  # external URL：调用方自行 fetch

    def list_for_session(self) -> list[ArtifactRef]:
        """列出当前 session 所有 artifact."""
        out: list[ArtifactRef] = []
        if not self.session_dir.exists():
            return out
        for sub in self.session_dir.iterdir():
            if sub.is_dir():
                for f in sub.iterdir():
                    if f.is_file():
                        rel = f.relative_to(ARTIFACTS_DIR)
                        out.append(ArtifactRef(
                            uri=f"artifact://{rel.as_posix()}",
                            mime_type=_guess_mime(f.suffix),
                            summary=f.name,
                        ))
        return out


def _guess_mime(suffix: str) -> str:
    return {
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".json": "application/json",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".html": "text/html",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".mp3": "audio/mpeg",
    }.get(suffix.lower(), "application/octet-stream")
