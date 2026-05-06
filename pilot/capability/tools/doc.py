"""doc.create / doc.append — 飞书 Docx 工具.

设计:
  - `doc.create` 仅创建空文档，返回 doc_token + url
  - `doc.append` 调 LLM 生成 markdown，再批写入飞书 Docx 块
  - 大段 markdown 落盘到 filesystem_memory 作为 artifact，conversation 中只放 ref
  - 当无飞书 token 时回退到本地 .md 文件，保证离线测试可跑
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from pilot.context.filesystem_memory import FilesystemMemory

logger = logging.getLogger("pilot.tool.doc")


# ── 注册入口（registry 调用）──


def register_to(reg) -> None:
    reg.register(
        "doc.create",
        description="创建一个新的飞书 Docx 文档（仅创建空文档，标题由参数指定）",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "文档标题"},
                "folder_token": {"type": "string", "description": "目标文件夹 token（可选）"},
            },
            "required": ["title"],
        },
        read_only=False,
        namespace="pilot",
    )(doc_create)

    reg.register(
        "doc.append",
        description="向已创建的飞书 Docx 追加内容；如果 markdown 留空，工具会用 LLM 自动生成",
        input_schema={
            "type": "object",
            "properties": {
                "doc_token": {"type": "string", "description": "doc.create 返回的 doc_token"},
                "markdown": {"type": "string", "description": "要追加的 markdown（留空则 AI 生成）"},
                "intent": {"type": "string", "description": "用户原始意图（用于 AI 生成）"},
                "search_results": {
                    "description": "上游 web.search 注入的结果 [{title,url,snippet}]，用于让 LLM 引用真实数据",
                },
            },
            "required": ["doc_token"],
        },
        read_only=False,
        namespace="pilot",
    )(doc_append)


# ── 实现 ──


async def doc_create(*, title: str = "", folder_token: str = "", _ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """创建飞书 Docx，回退到本地文件."""
    feishu_app_id = os.getenv("FEISHU_APP_ID", "")
    feishu_app_secret = os.getenv("FEISHU_APP_SECRET", "")

    if feishu_app_id and feishu_app_id != "cli_your_app_id_here" and feishu_app_secret:
        try:
            from pilot.surface.feishu.client import get_feishu_client

            client = get_feishu_client()
            r = await client.docx_create(title=title or "[Agent-Pilot] 未命名文档",
                                         folder_token=folder_token or os.getenv("FEISHU_FOLDER_TOKEN", ""))
            doc_token = r.get("document", {}).get("document_id", "") or r.get("document_id", "")
            if doc_token:
                url = f"https://feishu.cn/docx/{doc_token}"
                logger.info("doc.create feishu: %s", url)
                return {
                    "doc_token": doc_token,
                    "url": url,
                    "title": title,
                    "source": "feishu",
                }
        except Exception as e:
            logger.warning("doc.create feishu fallback: %s", e)

    # 本地回退
    session_id = ""
    if _ctx and _ctx.get("session"):
        try:
            session_id = _ctx["session"].session_id
        except Exception:
            pass

    aid = f"doc_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    mem = FilesystemMemory(session_id=session_id)
    art = mem.store_text(
        f"# {title}\n\n（待生成内容）\n",
        kind="docs",
        mime_type="text/markdown",
        summary=title,
        tool="doc.create",
        step_id=(_ctx or {}).get("step_id", ""),
    )
    return {
        "doc_token": aid,
        "url": art.uri,
        "title": title,
        "source": "local",
        "artifact": art.to_dict(),
    }


async def doc_append(
    *,
    doc_token: str,
    markdown: str = "",
    intent: str = "",
    search_results: Any = None,
    _ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """向 doc 追加内容；markdown 留空则 LLM 自动生成."""
    if not markdown:
        markdown = await _generate_markdown(
            intent=intent or "（请生成一段结构化方案）",
            search_results=_normalize_search_results(search_results),
            _ctx=_ctx,
        )

    feishu_app_id = os.getenv("FEISHU_APP_ID", "")
    if feishu_app_id and feishu_app_id != "cli_your_app_id_here":
        try:
            from pilot.surface.feishu.client import get_feishu_client

            client = get_feishu_client()
            blocks = _markdown_to_feishu_blocks(markdown)
            wrote = await client.docx_append_blocks(doc_token=doc_token, blocks=blocks)
            logger.info("doc.append feishu: %d blocks → %s", wrote, doc_token)
            return {
                "doc_token": doc_token,
                "wrote_blocks": wrote,
                "markdown_chars": len(markdown),
                "source": "feishu",
            }
        except Exception as e:
            logger.warning("doc.append feishu fallback: %s", e)

    # 本地回退：把 markdown 写到 doc artifact 上
    session_id = ""
    if _ctx and _ctx.get("session"):
        try:
            session_id = _ctx["session"].session_id
        except Exception:
            pass
    mem = FilesystemMemory(session_id=session_id)
    art = mem.store_text(
        markdown,
        kind="docs",
        mime_type="text/markdown",
        summary=markdown[:120],
        tool="doc.append",
        step_id=(_ctx or {}).get("step_id", ""),
    )
    return {
        "doc_token": doc_token,
        "wrote_blocks": markdown.count("\n") + 1,
        "markdown_chars": len(markdown),
        "markdown_artifact": art.to_dict(),
        "source": "local",
    }


# ── LLM 生成 markdown ──


def _normalize_search_results(raw: Any) -> list[dict[str, str]]:
    """允许传入 list / dict / json string / placeholder 残留 → 统一成 [{title,url,snippet}].

    Orchestrator 已替换 ${sX.results} 占位符，但兜底时若仍为字符串就 json.loads。
    """
    if not raw:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("$") or not s:
            return []
        try:
            raw = json.loads(s)
        except Exception:
            return []
    if isinstance(raw, dict):
        raw = raw.get("results") or raw.get("items") or []
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, dict):
            t = str(item.get("title", ""))[:200]
            u = str(item.get("url", ""))[:500]
            s = str(item.get("snippet", "") or item.get("desc", ""))[:400]
            if t or u:
                out.append({"title": t, "url": u, "snippet": s})
    return out[:10]


async def _generate_markdown(
    *,
    intent: str,
    search_results: list[dict[str, str]] | None = None,
    _ctx: dict[str, Any] | None = None,
) -> str:
    try:
        from pilot.llm.client import default_client

        cite_block = ""
        if search_results:
            lines = ["\n参考资料（请在正文中以脚注形式 [1] [2] 引用真实数据，不要瞎编）："]
            for i, r in enumerate(search_results[:5], 1):
                lines.append(f"[{i}] {r.get('title','')}\n    URL: {r.get('url','')}\n    摘要: {r.get('snippet','')}")
            cite_block = "\n".join(lines)

        prompt = f"""请根据用户意图生成一份结构化的中文方案文档（Markdown 格式）。

用户意图：{intent}
{cite_block}

要求：
1. 字数 1500-3000 字
2. 至少有 5 个二级标题（##）
3. 包含数据/案例/风险三类信息
4. 不要寒暄、不要"以下是为您生成的"之类元语言
5. 直接输出 markdown 正文
6. 如果上面有参考资料，必须在正文里以 [1] [2] 形式引用，并在文末列"## 参考资料"段落含真实 URL
"""
        client = default_client()
        result = await asyncio.wait_for(
            client.chat(
                system="你是 Agent-Pilot 的资深写作员，擅长结构化方案与汇报文档。",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=4096,
            ),
            timeout=60.0,
        )
        if result.get("raw", {}).get("_mock"):
            return _fallback_markdown(intent)
        text = result.get("text", "")
        if not text:
            for block in result.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    t = block.get("text", "").strip()
                    if len(t) >= 200:
                        return t
        if len(text) >= 200:
            return text
        return _fallback_markdown(intent)
    except asyncio.TimeoutError:
        logger.warning("doc.append LLM timeout (60s), using fallback")
        return _fallback_markdown(intent)
    except Exception as e:
        logger.warning("doc.append LLM failed, using fallback: %s", e)
        return _fallback_markdown(intent)


def _fallback_markdown(intent: str) -> str:
    return f"""# {intent[:60]}

## 1. 背景与现状

围绕「{intent}」的背景与当前现状梳理。本节用于阐述任务发起的业务上下文、上一阶段的进展、以及当前需要面对的关键变化。建议补充：行业宏观数据、当前痛点的具体表现、关键利益相关方的诉求。

## 2. 目标与受众

- **核心目标**：明确"做什么、给谁、什么时候要"。这是后续所有决策的锚点。
- **受众画像**：本次产出主要面向上级 / 同事 / 客户中的哪一类，他们最关心的是结果、过程还是数据。
- **时间节点**：DDL 何时？是否需要分阶段交付？

## 3. 方案设计

### 3.1 阶段一 · 现状盘点

把当前已有的资源、阻碍、外部条件梳理清楚，不要急着提方案。

### 3.2 阶段二 · 核心动作

围绕目标提出 2-3 个核心动作。每个动作要有明确负责人、产出物、验收标准。

### 3.3 阶段三 · 复盘与调整

设置 1-2 个 checkpoint，及时根据反馈调整。

## 4. 数据与案例

- **行业数据**：补充 2-3 条权威数据源的关键指标（市场规模、增速、占比）。
- **典型案例**：补充 1-2 个同类项目的成功 / 失败经验，提炼可复用的方法论。
- **内部基线**：与公司过往项目对比，确认本项目的位置。

## 5. 风险与对策

| 风险类型 | 触发条件 | 缓解策略 |
|---|---|---|
| 资源不足 | 关键人力请假 | 提前预留 buffer，关键路径双人备份 |
| 进度滞后 | 单点阻塞 | 拆分子任务，缩短反馈环 |
| 质量风险 | 验收标准模糊 | 在 Sprint 启动前签字"完成定义" |

## 6. 结论与下一步

围绕本议题，建议在本周内：(1) 完成现状盘点；(2) 召集关键人员对齐目标；(3) 启动阶段二的核心动作。

> 本段由 Agent-Pilot 兜底生成；如需更高质量内容，请配置 LLM API key 后重新触发。
"""


# ── markdown → 飞书 block（精简版）──


def _markdown_to_feishu_blocks(md: str) -> list[dict[str, Any]]:
    """将 markdown 转为飞书 Docx block children 格式.

    飞书 block_type: 2=text, 3=heading1, 4=heading2, ..., 12=bullet, 13=ordered
    """
    blocks = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            text = m.group(2)
            blocks.append({
                "block_type": 2 + level,
                f"heading{level}": {
                    "elements": [{"text_run": {"content": text, "text_element_style": {}}}],
                    "style": {},
                },
            })
            continue
        if line.startswith("- ") or line.startswith("* "):
            blocks.append({
                "block_type": 12,
                "bullet": {
                    "elements": [{"text_run": {"content": line[2:].strip(), "text_element_style": {}}}],
                    "style": {},
                },
            })
            continue
        if line.startswith("|") and "|" in line[1:]:
            cells = [c.strip() for c in line.strip("|").split("|") if c.strip() and c.strip() != "---"]
            if cells:
                blocks.append({
                    "block_type": 2,
                    "text": {
                        "elements": [{"text_run": {"content": " | ".join(cells), "text_element_style": {}}}],
                        "style": {},
                    },
                })
            continue
        if line.startswith("> "):
            blocks.append({
                "block_type": 2,
                "text": {
                    "elements": [{"text_run": {"content": line[2:].strip(), "text_element_style": {}}}],
                    "style": {},
                },
            })
            continue
        blocks.append({
            "block_type": 2,
            "text": {
                "elements": [{"text_run": {"content": line, "text_element_style": {}}}],
                "style": {},
            },
        })
    return blocks
