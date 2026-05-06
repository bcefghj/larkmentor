"""ContextPack – PRD §7 落地.

Before executing a doc/slide/canvas chain, the Agent first surfaces what it
intends to use as input ("已读 N 条 IM"、"关联文档"、"用户补充资料") and
asks the owner to confirm or supplement. The user can:
  - 直接生成: proceed with the auto-collected context
  - 添加资料: paste link / upload file / add note
  - 调整任务目标: refine intent before execution

The pack is a plain-data structure stored to ``data/pilot_context_packs/{plan_id}.json``
so that the orchestrator and the Dashboard can pick it up.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_pilot.intel.context_pack")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PACK_DIR = PROJECT_ROOT / "data" / "pilot_context_packs"


@dataclass
class ContextItem:
    """One discrete piece of context."""
    kind: str  # "im_thread" | "doc" | "file" | "link" | "user_note"
    title: str
    summary: str = ""
    url: str = ""
    token: str = ""  # feishu doc_token / file_token
    source: str = "auto"  # "auto" | "manual"
    added_ts: int = 0


@dataclass
class ContextPack:
    plan_id: str
    intent: str
    owner_open_id: str = ""
    output_requirements: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)
    items: List[ContextItem] = field(default_factory=list)
    missing_hints: List[str] = field(default_factory=list)
    status: str = "pending"  # pending | confirmed | abandoned
    created_ts: int = 0
    confirmed_ts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "items": [asdict(i) for i in self.items],
        }

    def add_item(self, item: ContextItem) -> None:
        item.added_ts = item.added_ts or int(time.time())
        self.items.append(item)


# ── Build / persist ──────────────────────────────────────────────────────────


def build_context_pack(
    plan_id: str,
    intent: str,
    *,
    owner_open_id: str = "",
    thread_messages: Optional[List[Dict[str, Any]]] = None,
    related_docs: Optional[List[Dict[str, Any]]] = None,
) -> ContextPack:
    """Assemble the auto-context for an intent. Heuristic + summary."""
    pack = ContextPack(
        plan_id=plan_id,
        intent=intent,
        owner_open_id=owner_open_id,
        created_ts=int(time.time()),
        output_requirements=_infer_output_requirements(intent),
        constraints=_infer_constraints(intent),
    )
    # IM thread snapshot
    if thread_messages:
        last = thread_messages[-30:]
        snippet = "\n".join(
            f"- {m.get('sender', '?')}: {m.get('text', '')[:80]}"
            for m in last
        )
        pack.add_item(ContextItem(
            kind="im_thread",
            title=f"最近 {len(last)} 条 IM 讨论",
            summary=snippet[:600],
        ))
    if related_docs:
        for d in related_docs:
            pack.add_item(ContextItem(
                kind="doc",
                title=str(d.get("title", "")),
                summary=str(d.get("summary", ""))[:300],
                url=str(d.get("url", "")),
                token=str(d.get("token", "")),
            ))
    pack.missing_hints = _suggest_missing(intent, pack)
    return pack


def _infer_output_requirements(intent: str) -> Dict[str, Any]:
    req: Dict[str, Any] = {"language": "zh-CN"}
    intent_lo = intent.lower()
    if "ppt" in intent_lo or "演示" in intent or "汇报" in intent:
        m = re.search(r"(\d+)\s*[页張张]", intent)
        if m:
            req["pages"] = int(m.group(1))
        else:
            req["pages"] = 8
        req["format"] = "pptx+html"
    if "文档" in intent or "方案" in intent or "报告" in intent or "纪要" in intent:
        req["doc_format"] = "markdown"
        m = re.search(r"(\d+)\s*[字]", intent)
        if m:
            req["min_chars"] = int(m.group(1))
        else:
            req["min_chars"] = 1500
    if "画布" in intent or "白板" in intent or "架构图" in intent or "流程图" in intent:
        req["canvas"] = True
    if "演讲稿" in intent or "讲稿" in intent or "rehearse" in intent_lo:
        req["speaker_notes"] = True
    return req


def _infer_constraints(intent: str) -> Dict[str, Any]:
    constraints: Dict[str, Any] = {}
    if any(k in intent for k in ("老板", "领导", "高管")):
        constraints["audience"] = "leadership"
        constraints["tone"] = "concise+strategic"
    elif any(k in intent for k in ("客户", "甲方")):
        constraints["audience"] = "customer"
        constraints["tone"] = "professional+benefit-driven"
    if "下周" in intent or "明天" in intent or "今天" in intent:
        constraints["urgency"] = "high"
    return constraints


def _suggest_missing(intent: str, pack: ContextPack) -> List[str]:
    hints: List[str] = []
    if not pack.items:
        hints.append("未读取任何 IM 上下文，建议补充本次需求的相关讨论或链接")
    has_data_request = any(k in intent for k in ("数据", "复盘", "对比", "调研"))
    if has_data_request and not any(i.kind in ("doc", "file", "link") for i in pack.items):
        hints.append("意图涉及数据/复盘/调研，建议补充原始数据或历史报告")
    if "客户" in intent and not any(i.kind == "doc" for i in pack.items):
        hints.append("意图涉及客户，建议关联客户档案或前期方案文档")
    return hints


def save_pack(pack: ContextPack) -> Path:
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    path = PACK_DIR / f"{pack.plan_id}.json"
    path.write_text(json.dumps(pack.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def load_pack(plan_id: str) -> Optional[ContextPack]:
    path = PACK_DIR / f"{plan_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = [ContextItem(**i) for i in data.get("items", [])]
        data["items"] = items
        return ContextPack(**data)
    except Exception as e:
        logger.warning("load_pack[%s] failed: %s", plan_id, e)
        return None


def confirm_pack(plan_id: str) -> bool:
    pack = load_pack(plan_id)
    if not pack:
        return False
    pack.status = "confirmed"
    pack.confirmed_ts = int(time.time())
    save_pack(pack)
    return True


def add_user_supplied_item(plan_id: str, *, kind: str, title: str,
                           summary: str = "", url: str = "") -> bool:
    pack = load_pack(plan_id)
    if not pack:
        return False
    pack.add_item(ContextItem(
        kind=kind, title=title, summary=summary, url=url, source="manual",
    ))
    pack.missing_hints = _suggest_missing(pack.intent, pack)
    save_pack(pack)
    return True


__all__ = [
    "ContextItem",
    "ContextPack",
    "build_context_pack",
    "save_pack",
    "load_pack",
    "confirm_pack",
    "add_user_supplied_item",
]
