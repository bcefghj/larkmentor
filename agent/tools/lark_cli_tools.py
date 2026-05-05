"""Lark CLI Tools · 封装 @larksuite/cli 24+ AI Agent Skills.

通过 subprocess 桥接已安装的 ``@larksuite/cli``，为 Agent 提供飞书全平台操作能力。
支持 IM / Doc / Calendar / Sheets / Whiteboard / Slides 六大技能域，每个方法
都有超时控制、结构化输出和 graceful degradation（CLI 未安装时返回 mock）。

Ref: https://github.com/larksuite/cli

Usage::

    from agent.tools.lark_cli_tools import LarkCLIBridge, register_lark_tools
    from core.agent_pilot.harness.tool_registry import ToolRegistry

    bridge = LarkCLIBridge()
    registry = ToolRegistry()
    register_lark_tools(registry, bridge=bridge)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger("agent.tools.lark_cli")

from .registry import tool

DEFAULT_TIMEOUT = 30


@dataclass
class CLIResult:
    """Structured result from a CLI invocation."""

    ok: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    provider: str = "lark-cli"
    is_mock: bool = False

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"ok": self.ok, "provider": self.provider}
        if self.ok:
            out.update(self.data)
        else:
            out["error"] = self.error
        if self.is_mock:
            out["is_mock"] = True
        return out


class LarkCLIBridge:
    """Bridge to ``@larksuite/cli``.

    Discovers the CLI binary at construction time. If absent, all methods
    return mock responses with ``is_mock=True`` so downstream consumers
    can still exercise their logic paths.

    Parameters
    ----------
    cli_names
        Candidate binary names to search in ``$PATH``.
    default_timeout
        Default subprocess timeout in seconds.
    """

    def __init__(
        self,
        cli_names: tuple[str, ...] = ("lark-cli", "lark"),
        default_timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._cli_path: Optional[str] = None
        self._default_timeout = default_timeout
        self._available: Optional[bool] = None
        self._cli_names = cli_names
        self._discover()

    # ── Discovery ──

    def _discover(self) -> None:
        for name in self._cli_names:
            path = shutil.which(name)
            if path:
                self._cli_path = path
                self._available = True
                logger.info("lark_cli_found", path=path)
                return
        self._available = False
        logger.warning(
            "lark_cli_not_found",
            searched=self._cli_names,
            hint="Install via: npm install -g @larksuite/cli",
        )

    @property
    def available(self) -> bool:
        return bool(self._available)

    # ── Low-level runner ──

    def _run(
        self,
        skill: str,
        action: str,
        args: List[str],
        *,
        timeout: Optional[int] = None,
    ) -> CLIResult:
        """Execute ``lark-cli <skill> <action> [args] --output json``."""
        if not self.available:
            return self._mock(skill, action, args)

        cmd = [self._cli_path, skill, action, *args, "--output", "json"]  # type: ignore[list-item]
        t = timeout or self._default_timeout
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=t,
            )
        except subprocess.TimeoutExpired:
            logger.warning("lark_cli_timeout", skill=skill, action=action, timeout=t)
            return CLIResult(ok=False, error=f"timeout after {t}s")
        except FileNotFoundError:
            logger.error("lark_cli_binary_vanished", path=self._cli_path)
            self._available = False
            return self._mock(skill, action, args)
        except Exception as exc:
            logger.error("lark_cli_exec_error", error=str(exc))
            return CLIResult(ok=False, error=str(exc))

        if proc.returncode != 0:
            stderr_snippet = (proc.stderr or "").strip()[:300]
            logger.debug(
                "lark_cli_nonzero",
                skill=skill,
                action=action,
                code=proc.returncode,
                stderr=stderr_snippet,
            )
            return CLIResult(ok=False, error=stderr_snippet or f"exit code {proc.returncode}")

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            data = {"raw": proc.stdout.strip()[:2000]}
        return CLIResult(ok=True, data=data)

    def _mock(self, skill: str, action: str, args: List[str]) -> CLIResult:
        """Return a plausible mock response when the CLI is not installed."""
        logger.debug("lark_cli_mock", skill=skill, action=action)
        return CLIResult(
            ok=True,
            data={
                "mock": True,
                "skill": skill,
                "action": action,
                "message": "CLI not installed; returning mock response",
            },
            is_mock=True,
        )

    # ── lark-im ──

    def im_send(
        self,
        chat_id: str,
        text: str,
        *,
        msg_type: str = "text",
        timeout: int = 15,
    ) -> CLIResult:
        """Send a message to a Feishu chat."""
        if not chat_id or not text:
            return CLIResult(ok=False, error="chat_id and text are required")
        args = ["--chat-id", chat_id, "--text", text[:5000]]
        if msg_type != "text":
            args.extend(["--type", msg_type])
        return self._run("im", "send", args, timeout=timeout)

    def im_fetch(
        self,
        chat_id: str,
        *,
        limit: int = 20,
        timeout: int = 15,
    ) -> CLIResult:
        """Fetch recent messages from a Feishu chat."""
        if not chat_id:
            return CLIResult(ok=False, error="chat_id is required")
        args = ["--chat-id", chat_id, "--limit", str(limit)]
        return self._run("im", "fetch", args, timeout=timeout)

    # ── lark-doc ──

    def doc_create(
        self,
        title: str = "",
        content: str = "",
        folder: str = "",
    ) -> CLIResult:
        """Create a Feishu document."""
        args = ["--title", title or "Agent-Pilot Doc"]
        if content:
            args.extend(["--content", content[:10000]])
        if folder:
            args.extend(["--folder", folder])
        return self._run("doc", "create", args)

    def doc_update(
        self,
        doc_id: str,
        content: str,
        *,
        mode: str = "append",
    ) -> CLIResult:
        """Update (append / replace) a Feishu document."""
        if not doc_id or not content:
            return CLIResult(ok=False, error="doc_id and content are required")
        args = ["--id", doc_id, "--content", content[:10000], "--mode", mode]
        return self._run("doc", "update", args)

    def doc_read(
        self,
        url: str = "",
        doc_id: str = "",
    ) -> CLIResult:
        """Read a Feishu document's content."""
        args: List[str] = []
        if url:
            args.extend(["--url", url])
        elif doc_id:
            args.extend(["--id", doc_id])
        else:
            return CLIResult(ok=False, error="url or doc_id is required")
        return self._run("doc", "read", args)

    # ── lark-calendar ──

    def calendar_query(
        self,
        *,
        days: int = 7,
        calendar_id: str = "",
        timeout: int = 15,
    ) -> CLIResult:
        """Query calendar events for the next N days."""
        args = ["--days", str(days)]
        if calendar_id:
            args.extend(["--calendar-id", calendar_id])
        return self._run("calendar", "query", args, timeout=timeout)

    def calendar_create_event(
        self,
        title: str,
        start: str,
        end: str,
        *,
        attendees: str = "",
    ) -> CLIResult:
        """Create a calendar event."""
        if not title or not start or not end:
            return CLIResult(ok=False, error="title, start, and end are required")
        args = ["--title", title, "--start", start, "--end", end]
        if attendees:
            args.extend(["--attendees", attendees])
        return self._run("calendar", "create", args)

    # ── lark-sheets ──

    def sheets_read(
        self,
        url: str = "",
        sheet_id: str = "",
        *,
        range_: str = "",
    ) -> CLIResult:
        """Read cells from a Feishu spreadsheet."""
        args: List[str] = []
        if url:
            args.extend(["--url", url])
        elif sheet_id:
            args.extend(["--id", sheet_id])
        else:
            return CLIResult(ok=False, error="url or sheet_id is required")
        if range_:
            args.extend(["--range", range_])
        return self._run("sheets", "read", args)

    def sheets_write(
        self,
        sheet_id: str,
        range_: str,
        values: List[List[Any]],
    ) -> CLIResult:
        """Write cells to a Feishu spreadsheet."""
        if not sheet_id or not range_ or not values:
            return CLIResult(ok=False, error="sheet_id, range_, and values are required")
        values_json = json.dumps(values, ensure_ascii=False)
        args = ["--id", sheet_id, "--range", range_, "--values", values_json]
        return self._run("sheets", "write", args)

    # ── lark-whiteboard ──

    def whiteboard_create(
        self,
        title: str = "",
        folder: str = "",
    ) -> CLIResult:
        """Create a new Feishu whiteboard."""
        args = ["--title", title or "Agent-Pilot Whiteboard"]
        if folder:
            args.extend(["--folder", folder])
        return self._run("whiteboard", "create", args)

    def whiteboard_add_shape(
        self,
        board_id: str,
        shape_type: str = "rect",
        *,
        x: int = 0,
        y: int = 0,
        width: int = 200,
        height: int = 100,
        text: str = "",
    ) -> CLIResult:
        """Add a shape to an existing whiteboard."""
        if not board_id:
            return CLIResult(ok=False, error="board_id is required")
        args = [
            "--board-id",
            board_id,
            "--shape",
            shape_type,
            "--x",
            str(x),
            "--y",
            str(y),
            "--width",
            str(width),
            "--height",
            str(height),
        ]
        if text:
            args.extend(["--text", text[:2000]])
        return self._run("whiteboard", "add-shape", args)

    # ── lark-slides ──

    def slides_create(
        self,
        title: str = "",
        outline: str = "",
        template: str = "",
    ) -> CLIResult:
        """Create a Feishu slide presentation."""
        args = ["--title", title or "Agent-Pilot Presentation"]
        if outline:
            args.extend(["--outline", outline[:5000]])
        if template:
            args.extend(["--template", template])
        return self._run("slides", "create", args)

    def slides_add_page(
        self,
        slides_id: str,
        content: str,
        *,
        layout: str = "title_content",
    ) -> CLIResult:
        """Add a page to an existing slide presentation."""
        if not slides_id or not content:
            return CLIResult(ok=False, error="slides_id and content are required")
        args = ["--id", slides_id, "--content", content[:5000], "--layout", layout]
        return self._run("slides", "add-page", args)


# ────────────────────────────────────────────────────────────────
# @tool 装饰器注册（用于 agent/tools 层的简单注册表）
# ────────────────────────────────────────────────────────────────

_bridge: Optional[LarkCLIBridge] = None


def _get_bridge() -> LarkCLIBridge:
    global _bridge
    if _bridge is None:
        _bridge = LarkCLIBridge()
    return _bridge


@tool(name="lark.im.send", description="通过飞书 CLI 发送 IM 消息", permission="write", team="any")
def cli_im_send(chat_id: str = "", text: str = "", msg_type: str = "text") -> Dict[str, Any]:
    return _get_bridge().im_send(chat_id, text, msg_type=msg_type).to_dict()


@tool(name="lark.im.fetch", description="通过飞书 CLI 拉取聊天消息", permission="readonly", team="any")
def cli_im_fetch(chat_id: str = "", limit: int = 20) -> Dict[str, Any]:
    return _get_bridge().im_fetch(chat_id, limit=limit).to_dict()


@tool(name="lark.doc.create", description="通过飞书 CLI 创建文档", permission="write", team="any")
def cli_doc_create(title: str = "", content: str = "", folder: str = "") -> Dict[str, Any]:
    return _get_bridge().doc_create(title, content, folder).to_dict()


@tool(name="lark.doc.update", description="通过飞书 CLI 更新文档内容", permission="write", team="any")
def cli_doc_update(doc_id: str = "", content: str = "", mode: str = "append") -> Dict[str, Any]:
    return _get_bridge().doc_update(doc_id, content, mode=mode).to_dict()


@tool(name="lark.doc.read", description="通过飞书 CLI 读取文档内容", permission="readonly", team="any")
def cli_doc_read(url: str = "", doc_id: str = "") -> Dict[str, Any]:
    return _get_bridge().doc_read(url, doc_id).to_dict()


@tool(name="lark.calendar.query", description="通过飞书 CLI 查询日程安排", permission="readonly", team="any")
def cli_calendar_query(days: int = 7, calendar_id: str = "") -> Dict[str, Any]:
    return _get_bridge().calendar_query(days=days, calendar_id=calendar_id).to_dict()


@tool(name="lark.calendar.create_event", description="通过飞书 CLI 创建日历事件", permission="write", team="any")
def cli_calendar_create_event(title: str = "", start: str = "", end: str = "", attendees: str = "") -> Dict[str, Any]:
    return _get_bridge().calendar_create_event(title, start, end, attendees=attendees).to_dict()


@tool(name="lark.sheets.read", description="通过飞书 CLI 读取表格数据", permission="readonly", team="any")
def cli_sheets_read(url: str = "", sheet_id: str = "", range_: str = "") -> Dict[str, Any]:
    return _get_bridge().sheets_read(url, sheet_id, range_=range_).to_dict()


@tool(name="lark.sheets.write", description="通过飞书 CLI 写入表格数据", permission="write", team="any")
def cli_sheets_write(sheet_id: str = "", range_: str = "", values: str = "[]") -> Dict[str, Any]:
    try:
        parsed = json.loads(values) if isinstance(values, str) else values
    except json.JSONDecodeError:
        return {"ok": False, "error": "values must be valid JSON array of arrays"}
    return _get_bridge().sheets_write(sheet_id, range_, parsed).to_dict()


@tool(name="lark.whiteboard.create", description="通过飞书 CLI 创建白板", permission="write", team="any")
def cli_whiteboard_create(title: str = "", folder: str = "") -> Dict[str, Any]:
    return _get_bridge().whiteboard_create(title, folder).to_dict()


@tool(name="lark.whiteboard.add_shape", description="通过飞书 CLI 在白板上添加形状", permission="write", team="any")
def cli_whiteboard_add_shape(
    board_id: str = "",
    shape_type: str = "rect",
    x: int = 0,
    y: int = 0,
    width: int = 200,
    height: int = 100,
    text: str = "",
) -> Dict[str, Any]:
    return (
        _get_bridge()
        .whiteboard_add_shape(
            board_id,
            shape_type,
            x=x,
            y=y,
            width=width,
            height=height,
            text=text,
        )
        .to_dict()
    )


@tool(name="lark.slides.create", description="通过飞书 CLI 创建幻灯片", permission="write", team="any")
def cli_slides_create(title: str = "", outline: str = "", template: str = "") -> Dict[str, Any]:
    return _get_bridge().slides_create(title, outline, template).to_dict()


@tool(name="lark.slides.add_page", description="通过飞书 CLI 为幻灯片添加页面", permission="write", team="any")
def cli_slides_add_page(slides_id: str = "", content: str = "", layout: str = "title_content") -> Dict[str, Any]:
    return _get_bridge().slides_add_page(slides_id, content, layout=layout).to_dict()


# ────────────────────────────────────────────────────────────────
# register_lark_tools(): 注册到 harness ToolRegistry
# ────────────────────────────────────────────────────────────────


def register_lark_tools(
    registry: Any,
    *,
    bridge: Optional[LarkCLIBridge] = None,
) -> None:
    """Register all Lark CLI tools into a harness ``ToolRegistry``.

    Parameters
    ----------
    registry
        An instance of ``core.agent_pilot.harness.tool_registry.ToolRegistry``.
    bridge
        Optional pre-configured ``LarkCLIBridge``. If *None*, a default one
        is created lazily.
    """
    from core.agent_pilot.harness.tool_registry import build_tool

    b = bridge or _get_bridge()

    _specs = [
        # ── IM ──
        {
            "name": "lark.im.send",
            "description": "通过飞书 CLI 发送 IM 消息",
            "fn": lambda args, ctx, _b=b: _b.im_send(
                args.get("chat_id", ""),
                args.get("text", ""),
                msg_type=args.get("msg_type", "text"),
            ).to_dict(),
            "readonly": False,
            "category": "im",
            "timeout_sec": 15,
            "parameters": {
                "chat_id": {"type": "string", "desc": "目标聊天 ID"},
                "text": {"type": "string", "desc": "消息正文"},
                "msg_type": {"type": "string", "desc": "消息类型 (text/interactive/image)"},
            },
        },
        {
            "name": "lark.im.fetch",
            "description": "通过飞书 CLI 拉取聊天消息记录",
            "fn": lambda args, ctx, _b=b: _b.im_fetch(
                args.get("chat_id", ""),
                limit=int(args.get("limit", 20)),
            ).to_dict(),
            "readonly": True,
            "category": "im",
            "timeout_sec": 15,
            "parameters": {
                "chat_id": {"type": "string", "desc": "聊天 ID"},
                "limit": {"type": "integer", "desc": "拉取条数，默认 20"},
            },
        },
        # ── Doc ──
        {
            "name": "lark.doc.create",
            "description": "通过飞书 CLI 创建云文档",
            "fn": lambda args, ctx, _b=b: _b.doc_create(
                args.get("title", ""),
                args.get("content", ""),
                args.get("folder", ""),
            ).to_dict(),
            "readonly": False,
            "category": "doc",
            "timeout_sec": 30,
            "parameters": {
                "title": {"type": "string", "desc": "文档标题"},
                "content": {"type": "string", "desc": "文档初始内容（markdown）"},
                "folder": {"type": "string", "desc": "目标文件夹 token"},
            },
        },
        {
            "name": "lark.doc.update",
            "description": "通过飞书 CLI 更新云文档内容",
            "fn": lambda args, ctx, _b=b: _b.doc_update(
                args.get("doc_id", ""),
                args.get("content", ""),
                mode=args.get("mode", "append"),
            ).to_dict(),
            "readonly": False,
            "category": "doc",
            "timeout_sec": 30,
            "parameters": {
                "doc_id": {"type": "string", "desc": "文档 ID"},
                "content": {"type": "string", "desc": "要追加/替换的内容"},
                "mode": {"type": "string", "desc": "写入模式: append / replace"},
            },
        },
        {
            "name": "lark.doc.read",
            "description": "通过飞书 CLI 读取云文档内容",
            "fn": lambda args, ctx, _b=b: _b.doc_read(
                url=args.get("url", ""),
                doc_id=args.get("doc_id", ""),
            ).to_dict(),
            "readonly": True,
            "category": "doc",
            "timeout_sec": 30,
            "parameters": {
                "url": {"type": "string", "desc": "文档 URL"},
                "doc_id": {"type": "string", "desc": "文档 ID（与 url 二选一）"},
            },
        },
        # ── Calendar ──
        {
            "name": "lark.calendar.query",
            "description": "通过飞书 CLI 查询日程安排",
            "fn": lambda args, ctx, _b=b: _b.calendar_query(
                days=int(args.get("days", 7)),
                calendar_id=args.get("calendar_id", ""),
            ).to_dict(),
            "readonly": True,
            "category": "calendar",
            "timeout_sec": 15,
            "parameters": {
                "days": {"type": "integer", "desc": "查询未来 N 天的日程"},
                "calendar_id": {"type": "string", "desc": "日历 ID（可选）"},
            },
        },
        {
            "name": "lark.calendar.create_event",
            "description": "通过飞书 CLI 创建日历事件",
            "fn": lambda args, ctx, _b=b: _b.calendar_create_event(
                args.get("title", ""),
                args.get("start", ""),
                args.get("end", ""),
                attendees=args.get("attendees", ""),
            ).to_dict(),
            "readonly": False,
            "category": "calendar",
            "timeout_sec": 15,
            "parameters": {
                "title": {"type": "string", "desc": "事件标题"},
                "start": {"type": "string", "desc": "开始时间 (ISO 8601)"},
                "end": {"type": "string", "desc": "结束时间 (ISO 8601)"},
                "attendees": {"type": "string", "desc": "参与人（逗号分隔 open_id）"},
            },
        },
        # ── Sheets ──
        {
            "name": "lark.sheets.read",
            "description": "通过飞书 CLI 读取电子表格数据",
            "fn": lambda args, ctx, _b=b: _b.sheets_read(
                url=args.get("url", ""),
                sheet_id=args.get("sheet_id", ""),
                range_=args.get("range", ""),
            ).to_dict(),
            "readonly": True,
            "category": "sheets",
            "timeout_sec": 30,
            "parameters": {
                "url": {"type": "string", "desc": "表格 URL"},
                "sheet_id": {"type": "string", "desc": "表格 ID（与 url 二选一）"},
                "range": {"type": "string", "desc": "单元格范围，如 A1:C10"},
            },
        },
        {
            "name": "lark.sheets.write",
            "description": "通过飞书 CLI 写入电子表格数据",
            "fn": lambda args, ctx, _b=b: _b.sheets_write(
                args.get("sheet_id", ""),
                args.get("range", ""),
                args.get("values", []),
            ).to_dict(),
            "readonly": False,
            "category": "sheets",
            "timeout_sec": 30,
            "parameters": {
                "sheet_id": {"type": "string", "desc": "表格 ID"},
                "range": {"type": "string", "desc": "写入范围"},
                "values": {"type": "array", "desc": "二维数组，行×列值"},
            },
        },
        # ── Whiteboard ──
        {
            "name": "lark.whiteboard.create",
            "description": "通过飞书 CLI 创建白板",
            "fn": lambda args, ctx, _b=b: _b.whiteboard_create(
                args.get("title", ""),
                args.get("folder", ""),
            ).to_dict(),
            "readonly": False,
            "category": "whiteboard",
            "timeout_sec": 30,
            "parameters": {
                "title": {"type": "string", "desc": "白板标题"},
                "folder": {"type": "string", "desc": "目标文件夹 token"},
            },
        },
        {
            "name": "lark.whiteboard.add_shape",
            "description": "通过飞书 CLI 在白板上添加形状",
            "fn": lambda args, ctx, _b=b: _b.whiteboard_add_shape(
                args.get("board_id", ""),
                args.get("shape_type", "rect"),
                x=int(args.get("x", 0)),
                y=int(args.get("y", 0)),
                width=int(args.get("width", 200)),
                height=int(args.get("height", 100)),
                text=args.get("text", ""),
            ).to_dict(),
            "readonly": False,
            "category": "whiteboard",
            "timeout_sec": 30,
            "parameters": {
                "board_id": {"type": "string", "desc": "白板 ID"},
                "shape_type": {"type": "string", "desc": "形状类型 (rect/circle/arrow/sticky)"},
                "x": {"type": "integer", "desc": "X 坐标"},
                "y": {"type": "integer", "desc": "Y 坐标"},
                "width": {"type": "integer", "desc": "宽度"},
                "height": {"type": "integer", "desc": "高度"},
                "text": {"type": "string", "desc": "形状内文本"},
            },
        },
        # ── Slides ──
        {
            "name": "lark.slides.create",
            "description": "通过飞书 CLI 创建幻灯片演示文稿",
            "fn": lambda args, ctx, _b=b: _b.slides_create(
                args.get("title", ""),
                args.get("outline", ""),
                args.get("template", ""),
            ).to_dict(),
            "readonly": False,
            "category": "slides",
            "timeout_sec": 30,
            "parameters": {
                "title": {"type": "string", "desc": "演示文稿标题"},
                "outline": {"type": "string", "desc": "大纲内容"},
                "template": {"type": "string", "desc": "模板名称"},
            },
        },
        {
            "name": "lark.slides.add_page",
            "description": "通过飞书 CLI 为幻灯片添加新页面",
            "fn": lambda args, ctx, _b=b: _b.slides_add_page(
                args.get("slides_id", ""),
                args.get("content", ""),
                layout=args.get("layout", "title_content"),
            ).to_dict(),
            "readonly": False,
            "category": "slides",
            "timeout_sec": 30,
            "parameters": {
                "slides_id": {"type": "string", "desc": "幻灯片 ID"},
                "content": {"type": "string", "desc": "页面内容（markdown）"},
                "layout": {"type": "string", "desc": "页面布局 (title_content/blank/section_header)"},
            },
        },
    ]

    for spec_dict in _specs:
        registry.register(
            build_tool(
                name=spec_dict["name"],
                description=spec_dict["description"],
                fn=spec_dict["fn"],
                parameters=spec_dict.get("parameters", {}),
                readonly=spec_dict.get("readonly", False),
                category=spec_dict.get("category", "lark"),
                timeout_sec=spec_dict.get("timeout_sec", DEFAULT_TIMEOUT),
                tags=["lark-cli"],
            )
        )

    logger.info("lark_tools_registered", count=len(_specs), cli_available=b.available)


def cli_available() -> bool:
    """Quick check if the Lark CLI binary is discoverable."""
    return _get_bridge().available
