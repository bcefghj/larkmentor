"""ContextService · PRD §7 上下文包构建（三档资料源）.

PRD §7.1 上下文 5 类来源：
1. 当前 IM 对话    → ``from_im_messages``
2. 关联文档        → ``add_link_material`` / ``fetch_feishu_doc``
3. 执行人补充资料  → ``add_user_upload``
4. 历史任务资产    → ``recall_history_artifacts``
5. 用户偏好与模板  → ``apply_memory_inheritance`` (P15 6 级 Memory 注入)

Q4 已结论：**三档资料源同时支持** —— 粘贴链接 / 上传文件 / 飞书 Wiki+Docx 真实 API。
本 Service 把这三档统一抽象为 ``UserMaterial`` / ``SourceDoc``。

设计：
- 飞书 API 调用通过依赖注入（``feishu_doc_fetcher``），离线测试用 stub
- ``recall_history_artifacts`` 使用现有 FlowMemory archival
  （不直接 import 避免破坏 P0/P1 隔离；通过 ``recaller`` 注入）
- ``build_context_pack`` 是主入口，从 Task + 用户补充组装出可用的 ContextPack
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..domain import (
    ContextPack,
    MaterialKind,
    SourceDoc,
    SourceMessage,
    UserMaterial,
)
from ..domain.context_pack import Constraints, OutputRequirements

logger = logging.getLogger("pilot.application.context_service")


# ── 类型注入接口 ────────────────────────────────────────────────────────────


# Feishu Doc fetcher: (doc_token: str) -> SourceDoc | None
FeishuDocFetcher = Callable[[str], Optional[SourceDoc]]
FeishuWikiFetcher = Callable[[str], Optional[SourceDoc]]
# History recaller: (query, top_k) -> [SourceDoc]
HistoryRecaller = Callable[[str, int], List[SourceDoc]]
# Memory MD resolver (6-tier): (tenant, workspace, dept, group, user, session) -> str
MemoryResolver = Callable[..., str]


# ── 解析工具 ────────────────────────────────────────────────────────────────


_FEISHU_DOC_PAT = re.compile(r"https?://[^\s]*feishu\.cn/(?:docx|wiki|sheets)/([A-Za-z0-9_-]+)")
_DOC_TOKEN_PAT = re.compile(r"^[A-Za-z0-9_-]{6,}$")


def parse_feishu_doc_token(url_or_token: str) -> Optional[str]:
    """从飞书 URL 或裸 token 解析 doc_token."""
    m = _FEISHU_DOC_PAT.search(url_or_token)
    if m:
        return m.group(1)
    if _DOC_TOKEN_PAT.match(url_or_token.strip()):
        return url_or_token.strip()
    return None


# ── 上下文构建器 ────────────────────────────────────────────────────────────


@dataclass
class ContextBuildOptions:
    """``ContextService.build_for_task`` 参数."""

    task_id: str
    task_goal: str
    owner_open_id: str
    intent_text: str = ""
    output_primary: str = "doc"   # "doc" | "ppt" | "canvas"
    output_pages: int = 0
    output_style: str = ""
    output_audience: str = ""
    deadline_ts: int = 0
    must_cite: bool = True
    must_validate: bool = True
    # 6-tier memory selectors
    tenant_id: str = "default"
    workspace_id: str = ""
    department_id: str = ""
    chat_id: str = ""
    user_id: str = ""
    session_id: str = ""


class ContextService:
    """构建标准 ContextPack（PRD §7.4）."""

    def __init__(
        self,
        *,
        feishu_doc_fetcher: Optional[FeishuDocFetcher] = None,
        feishu_wiki_fetcher: Optional[FeishuWikiFetcher] = None,
        history_recaller: Optional[HistoryRecaller] = None,
        memory_resolver: Optional[MemoryResolver] = None,
        upload_root: str = "data/uploads",
    ) -> None:
        self.feishu_doc_fetcher = feishu_doc_fetcher
        self.feishu_wiki_fetcher = feishu_wiki_fetcher
        self.history_recaller = history_recaller
        self.memory_resolver = memory_resolver
        self.upload_root = upload_root
        os.makedirs(upload_root, exist_ok=True)

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build(self, opts: ContextBuildOptions, *,
              im_messages: Optional[List[SourceMessage]] = None,
              user_materials: Optional[List[UserMaterial]] = None,
              extra_doc_refs: Optional[List[str]] = None,
              recall_history: bool = True) -> ContextPack:
        """组装 ContextPack。每个数据源都失败可降级（return 空字段）."""
        cp = ContextPack(
            task_id=opts.task_id,
            task_goal=opts.task_goal,
            owner_open_id=opts.owner_open_id,
            pack_id=f"ctx-{uuid.uuid4().hex[:10]}",
            created_ts=int(time.time()),
            output_requirements=OutputRequirements(
                primary=opts.output_primary,
                pages=opts.output_pages,
                style=opts.output_style,
                audience=opts.output_audience,
            ),
            constraints=Constraints(
                deadline_ts=opts.deadline_ts,
                must_cite=opts.must_cite,
                must_validate=opts.must_validate,
            ),
        )
        if im_messages:
            cp.source_messages = list(im_messages)

        if user_materials:
            cp.user_added_materials = list(user_materials)
            for m in user_materials:
                # 把上传/链接材料同时映射成 SourceDoc 摘要（便于规划器使用）
                if m.kind == MaterialKind.UPLOAD and m.file_path:
                    cp.source_docs.append(SourceDoc(
                        kind=MaterialKind.UPLOAD,
                        title=m.title or os.path.basename(m.file_path),
                        excerpt=m.body[:500] if m.body else "",
                        permission_ok=True,
                    ))
                elif m.kind == MaterialKind.LINK and m.url:
                    cp.source_docs.append(SourceDoc(
                        kind=MaterialKind.LINK,
                        title=m.title or m.url,
                        url=m.url,
                        excerpt=m.body[:500] if m.body else "",
                        permission_ok=True,
                    ))

        if extra_doc_refs:
            for ref in extra_doc_refs:
                doc = self.fetch_doc_by_ref(ref)
                if doc:
                    cp.source_docs.append(doc)

        if recall_history and self.history_recaller and opts.task_goal:
            try:
                recalled = self.history_recaller(opts.task_goal, 3) or []
                for d in recalled:
                    d.kind = MaterialKind.HISTORY_TASK
                    cp.source_docs.append(d)
            except Exception as e:
                logger.debug("history recall failed: %s", e)

        return cp

    # ── 数据源适配 ────────────────────────────────────────────────────────
    def fetch_doc_by_ref(self, ref: str) -> Optional[SourceDoc]:
        """智能解析 ref：飞书 URL → fetch；http(s) URL → LINK；裸 token → fetch."""
        ref = (ref or "").strip()
        if not ref:
            return None

        token = parse_feishu_doc_token(ref)
        if token:
            # 优先 docx，再 wiki
            if self.feishu_doc_fetcher:
                try:
                    d = self.feishu_doc_fetcher(token)
                    if d:
                        return d
                except Exception as e:
                    logger.debug("feishu_doc_fetcher failed: %s", e)
            if self.feishu_wiki_fetcher:
                try:
                    d = self.feishu_wiki_fetcher(token)
                    if d:
                        return d
                except Exception as e:
                    logger.debug("feishu_wiki_fetcher failed: %s", e)
            # token 解析成功但没 fetcher → 还是返回个占位
            return SourceDoc(
                kind=MaterialKind.FEISHU_DOC,
                title=f"飞书文档 {token[:8]}",
                doc_token=token,
                url=ref if ref.startswith("http") else "",
                permission_ok=False,
                summary="未配置飞书 fetcher，仅记录引用",
            )

        if ref.startswith("http"):
            return SourceDoc(
                kind=MaterialKind.LINK,
                title=ref,
                url=ref,
                permission_ok=True,
            )
        return None

    # ── 资料补充 ──────────────────────────────────────────────────────────
    def add_link_material(self, cp: ContextPack, *, url: str, note: str = "") -> UserMaterial:
        m = UserMaterial(kind=MaterialKind.LINK, url=url, note=note, title=url)
        cp.user_added_materials.append(m)
        # 同步 source_docs
        cp.source_docs.append(SourceDoc(
            kind=MaterialKind.LINK, title=url, url=url, summary=note, permission_ok=True,
        ))
        return m

    def add_user_upload(self, cp: ContextPack, *, file_path: str, title: str = "",
                        body_excerpt: str = "") -> UserMaterial:
        m = UserMaterial(
            kind=MaterialKind.UPLOAD, file_path=file_path,
            title=title or os.path.basename(file_path),
            body=body_excerpt,
        )
        cp.user_added_materials.append(m)
        cp.source_docs.append(SourceDoc(
            kind=MaterialKind.UPLOAD, title=m.title,
            excerpt=body_excerpt[:500], permission_ok=True,
        ))
        return m

    def add_inline_note(self, cp: ContextPack, *, note: str, title: str = "用户备注") -> UserMaterial:
        m = UserMaterial(kind=MaterialKind.LINK, body=note, title=title, note=note)
        cp.user_added_materials.append(m)
        return m

    # ── 6 级 Memory 注入预接口（P15 真正实现） ────────────────────────────
    def resolve_memory_md(self, opts: ContextBuildOptions) -> str:
        if not self.memory_resolver:
            return ""
        try:
            return self.memory_resolver(
                tenant=opts.tenant_id,
                workspace=opts.workspace_id,
                department=opts.department_id,
                group=opts.chat_id,
                user=opts.user_id,
                session=opts.session_id,
            ) or ""
        except Exception as e:
            logger.debug("memory_resolver failed: %s", e)
            return ""

    # ── 摘要 / 缺失提示（PRD §7.2 上下文确认卡片）────────────────────────
    def render_confirm_summary(self, cp: ContextPack) -> Dict[str, Any]:
        return {
            "task_goal": cp.task_goal,
            "msg_count": len(cp.source_messages),
            "doc_count": len(cp.source_docs),
            "user_material_count": len(cp.user_added_materials),
            "missing": cp.missing(),
            "has_min_info": cp.has_min_info(),
            "total_chars": cp.total_chars(),
            "output_primary": cp.output_requirements.primary,
            "output_audience": cp.output_requirements.audience,
            "output_style": cp.output_requirements.style,
            "deadline": cp.constraints.deadline_ts,
            "must_cite": cp.constraints.must_cite,
        }


_default_service: Optional[ContextService] = None


def default_context_service() -> ContextService:
    """惰性单例。可由调用方覆盖（注入 feishu fetcher 等）."""
    global _default_service
    if _default_service is None:
        _default_service = ContextService()
    return _default_service


__all__ = [
    "ContextService",
    "ContextBuildOptions",
    "default_context_service",
    "parse_feishu_doc_token",
    "FeishuDocFetcher",
    "FeishuWikiFetcher",
    "HistoryRecaller",
    "MemoryResolver",
]
