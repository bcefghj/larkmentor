"""LarkMentor MCP Server – stdio + SSE entrypoints.

This module is intentionally tolerant of MCP being unavailable:

* If the ``mcp`` package is installed, register the tools and start the
  selected transport.
* If not, fall back to a tiny HTTP JSON server on the same port so other
  Agents (or curl) can still call ``/list_tools`` and ``/call`` to drive
  LarkMentor.

Either way the tool implementations live in ``tools.py`` and stay testable
without touching the network.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .tools import TOOL_REGISTRY, call_tool, list_tools, to_json

logger = logging.getLogger("flowguard.mcp.server")


def _start_mcp_proper(transport: str, port: int) -> bool:
    """Try the official ``mcp`` SDK. Returns False if not available."""
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore
    except Exception:
        logger.warning("mcp package not installed; falling back to JSON HTTP server")
        return False

    server = FastMCP("LarkMentor")

    def _make_wrapper(name: str, fn):
        async def wrapper(**kwargs: Any) -> Any:
            return fn(**kwargs)
        wrapper.__name__ = name
        return wrapper

    for name, (fn, doc) in TOOL_REGISTRY.items():
        wrapper = _make_wrapper(name, fn)
        server.tool(name=name, description=doc)(wrapper)

    if transport == "stdio":
        server.run("stdio")
    else:
        server.run("sse", host="0.0.0.0", port=port)
    return True


def _render_visual_html() -> str:
    """Self-contained HTML page that lists every MCP tool and lets you call them."""
    tools = list_tools()
    # Build the tool list in JS so the page is one round-trip and tests stay simple.
    tools_json = json.dumps(tools, ensure_ascii=False)
    return (
        "<!doctype html>\n"
        "<html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>LarkMentor · MCP Visual</title>"
        "<meta name='lm-mcp-version' content='v-c-1.0'>"
        "<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap' rel='stylesheet'>"
        "<style>"
        ":root{--bg:#fafaf9;--bg2:#fff;--bg3:#f4f4f3;--fg:#0a0a09;--fg2:#4a4a48;"
        "--fg3:#8a8a87;--line:#e7e7e4;--accent:#3370FF;--accent-soft:#e8f0ff;--ok:#10B981;--bad:#EF4444}"
        "[data-theme='dark']{--bg:#0a0a09;--bg2:#131311;--bg3:#1c1c1a;--fg:#f5f5f3;--fg2:#b9b9b3;"
        "--fg3:#767672;--line:#2a2a27;--accent:#6699FF;--accent-soft:rgba(102,153,255,.12)}"
        "*{box-sizing:border-box;margin:0;padding:0}"
        "body{font-family:'Inter','PingFang SC',sans-serif;background:var(--bg);color:var(--fg);line-height:1.55}"
        "code,.mono{font-family:'JetBrains Mono',ui-monospace,Menlo,monospace}"
        "a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}"
        "button{font:inherit;color:inherit;cursor:pointer;background:none;border:0}"
        ".topbar{position:sticky;top:0;z-index:50;background:color-mix(in srgb,var(--bg) 88%,transparent);"
        "backdrop-filter:blur(12px) saturate(180%);border-bottom:1px solid var(--line)}"
        ".topbar .inner{max-width:1180px;margin:0 auto;padding:14px 28px;display:flex;align-items:center;justify-content:space-between;gap:24px}"
        ".logo{font-weight:800;display:inline-flex;align-items:center;gap:9px}"
        ".logo .dot{width:9px;height:9px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 4px color-mix(in srgb,var(--accent) 22%,transparent);animation:pulse 2.4s ease-in-out infinite}"
        ".nav{display:flex;align-items:center;gap:6px}"
        ".nav a{font-size:.82rem;color:var(--fg2);padding:8px 11px;border-radius:6px}"
        ".nav a:hover{background:var(--bg3);color:var(--fg);text-decoration:none}"
        ".theme{margin-left:6px;width:32px;height:32px;border-radius:50%;background:var(--bg3);color:var(--fg2);display:inline-flex;align-items:center;justify-content:center}"
        ".container{max-width:1180px;margin:0 auto;padding:36px 28px}"
        ".crumbs{font-family:'JetBrains Mono',monospace;font-size:.72rem;color:var(--accent);font-weight:600;letter-spacing:.1em;text-transform:uppercase}"
        "h1{font-size:clamp(1.7rem,3vw,2.2rem);font-weight:800;letter-spacing:-.02em;margin-top:8px}"
        "h1 em{font-style:normal;color:var(--accent)}"
        "p.lead{font-size:.95rem;color:var(--fg2);margin-top:10px;max-width:760px;line-height:1.7}"
        ".endpoints{margin-top:18px;display:flex;flex-wrap:wrap;gap:8px}"
        ".endpoints a{font-family:'JetBrains Mono',monospace;font-size:.78rem;padding:6px 12px;background:var(--bg2);border:1px solid var(--line);border-radius:999px;color:var(--fg2)}"
        ".endpoints a:hover{border-color:var(--accent);color:var(--accent);text-decoration:none}"
        ".grid{margin-top:28px;display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}"
        ".card{background:var(--bg2);border:1px solid var(--line);border-radius:12px;padding:16px;cursor:pointer;transition:all .15s;position:relative;opacity:0;transform:translateY(10px);animation:in .45s ease forwards}"
        ".card:hover{border-color:var(--accent);transform:translateY(-2px)}"
        ".card .nm{font-family:'JetBrains Mono',monospace;font-weight:700;font-size:.86rem;color:var(--accent)}"
        ".card .doc{margin-top:6px;font-size:.78rem;color:var(--fg2);line-height:1.55;min-height:48px}"
        ".card .badge{position:absolute;top:14px;right:14px;font-size:.62rem;padding:2px 7px;border-radius:999px;background:var(--accent-soft);color:var(--accent);font-weight:700}"
        ".card.alias .badge{background:var(--bg3);color:var(--fg3)}"
        ".panel{margin-top:24px;background:var(--bg2);border:1px solid var(--line);border-radius:12px;padding:18px}"
        ".panel .row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}"
        ".panel .row .nm{font-family:'JetBrains Mono',monospace;font-weight:700;color:var(--accent)}"
        ".panel .row button{padding:6px 14px;background:var(--accent);color:#fff;border-radius:6px;font-weight:600;font-size:.78rem}"
        ".panel textarea{width:100%;min-height:90px;padding:10px;border:1px solid var(--line);border-radius:8px;font-family:'JetBrains Mono',monospace;font-size:.78rem;background:var(--bg);color:var(--fg);resize:vertical}"
        ".panel textarea:focus{outline:0;border-color:var(--accent)}"
        ".result{margin-top:12px;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:12px;font-family:'JetBrains Mono',monospace;font-size:.76rem;color:var(--fg2);white-space:pre-wrap;max-height:380px;overflow:auto;line-height:1.55}"
        "footer{padding:36px 28px 56px;text-align:center;font-size:.78rem;color:var(--fg3);border-top:1px solid var(--line);margin-top:40px}"
        "@keyframes pulse{0%,100%{box-shadow:0 0 0 0 color-mix(in srgb,var(--accent) 40%,transparent)}50%{box-shadow:0 0 0 6px color-mix(in srgb,var(--accent) 0%,transparent)}}"
        "@keyframes in{to{opacity:1;transform:none}}"
        "</style></head><body>"
        "<nav class='topbar'><div class='inner'>"
        "<a class='logo' href='/'><span class='dot'></span>LarkMentor · <b style='color:var(--accent)'>MCP</b></a>"
        "<div class='nav'>"
        "<a href='/'>主页 ↗</a>"
        "<a href='/dashboard'>Dashboard</a>"
        "<a href='/mcp/tools'>Raw JSON</a>"
        "<a href='/health'>Health</a>"
        "<button class='theme' id='themeToggle' aria-label='theme'>☾</button>"
        "</div></div></nav>"
        "<main class='container'>"
        "<div class='crumbs'>MCP · MODEL CONTEXT PROTOCOL</div>"
        "<h1>LarkMentor 暴露的 <em>14 个工具</em>。</h1>"
        "<p class='lead'>通过 Model Context Protocol，LarkMentor 把"
        "「飞书工作状态感知 + Mentor 表达带教」暴露给任何 Agent。"
        "下面每张卡片都可点 → 实时 POST <code>/mcp/call</code>，结果回写到下方控制台。"
        "也可以直接 curl <code>/mcp/tools.json</code> 看完整 schema。</p>"
        "<div class='endpoints'>"
        "<a href='/mcp/tools' target='_blank'>GET /mcp/tools</a>"
        "<a href='/mcp/tools.json' target='_blank'>GET /mcp/tools.json</a>"
        "<a href='#try'>POST /mcp/call</a>"
        "<a href='/health' target='_blank'>GET /health</a>"
        "</div>"
        "<div class='grid' id='grid'></div>"
        "<section class='panel' id='try'>"
        "<div class='row'>"
        "<span style='font-weight:700'>在线 Try</span> · <span class='nm' id='curName'>—</span>"
        "<button id='runBtn'>POST /mcp/call →</button>"
        "</div>"
        "<textarea id='argsBox' placeholder='{ \"tool\": \"...\", \"arguments\": { ... } }'></textarea>"
        "<pre class='result' id='result'>// 点上方任一卡片，会自动填入示例参数 ……</pre>"
        "</section>"
        "</main>"
        "<footer>"
        "LarkMentor · MCP Visual · "
        "<a href='/'>主页</a> · "
        "<a href='/dashboard'>Dashboard</a> · "
        "<a href='/mcp/tools' target='_blank'>Raw JSON</a><br/>"
        "2026 飞书 AI 校园挑战赛 · 戴尚好 / 李洁盈"
        "</footer>"
        "<script>"
        "(function(){"
        "var TOOLS=" + tools_json + ";"
        "var DEMO={"
        "'get_focus_status':{open_id:'ou_demo_user_0001'},"
        "'classify_message':{user_open_id:'ou_demo_user_0001',sender_name:'\\u738b\\u603b',sender_id:'ou_boss_001',content:'\\u4eca\\u665a 10 \\u70b9 P0 \\u4e0a\\u7ebf',chat_name:'\\u6838\\u5fc3\\u5de5\\u4f5c\\u7fa4',chat_type:'team'},"
        "'get_recent_digest':{open_id:'ou_demo_user_0001',limit:5},"
        "'add_whitelist':{open_id:'ou_demo_user_0001',who:'ou_boss_001'},"
        "'rollback_decision':{open_id:'ou_demo_user_0001',decision_id:'dec_demo_001'},"
        "'query_memory':{open_id:'ou_demo_user_0001',query:'P0 \\u4e0a\\u7ebf',limit:3},"
        "'mentor_review_message':{open_id:'ou_demo_user_0001',message:'\\u597d\\u7684',recipient:'\\u738b\\u603b'},"
        "'mentor_clarify_task':{open_id:'ou_demo_user_0001',task_description:'\\u4f60\\u8ddf\\u4e00\\u4e0b\\u4e0b\\u5468\\u90a3\\u4e2a\\u9700\\u6c42',assigner:'\\u738b\\u603b'},"
        "'mentor_draft_weekly':{open_id:'ou_demo_user_0001',week_offset:0},"
        "'mentor_search_org_kb':{open_id:'ou_demo_user_0001',query:'\\u53d1\\u7248\\u516c\\u544a\\u600e\\u4e48\\u5199',top_k:3},"
        "'classify_readonly':{user_open_id:'ou_demo_user_0001',content:'\\u4f60\\u4e0b\\u5348\\u6709\\u7a7a\\u5417'},"
        "'skill_invoke':{open_id:'ou_demo_user_0001',skill:'mentor_review_message',input:{message:'\\u597d\\u7684'}},"
        "'memory_resolve':{open_id:'ou_demo_user_0001'},"
        "'list_skills':{}"
        "};"
        "var coachAlias=['coach_review_message','coach_clarify_task','coach_draft_weekly','coach_search_org_kb'];"
        "function render(){"
        "var g=document.getElementById('grid');g.innerHTML='';"
        "TOOLS.forEach(function(t,i){"
        "var alias=coachAlias.indexOf(t.name)>=0;"
        "var args=DEMO[t.name]||DEMO[t.name.replace('coach_','mentor_')]||{};"
        "var card=document.createElement('div');card.className='card'+(alias?' alias':'');"
        "card.style.animationDelay=(i*30)+'ms';"
        "card.innerHTML='<span class=\"badge\">'+(alias?'alias':'tool')+'</span>'+"
        "'<div class=\"nm\">'+t.name+'</div>'+"
        "'<div class=\"doc\">'+(t.doc||'')+'</div>';"
        "card.addEventListener('click',function(){pick(t.name,args);});"
        "g.appendChild(card);"
        "});"
        "}"
        "function pick(name,args){"
        "document.getElementById('curName').textContent=name;"
        "document.getElementById('argsBox').value=JSON.stringify({tool:name,arguments:args},null,2);"
        "document.getElementById('result').textContent='// \\u5df2\\u586b\\u5165\\u793a\\u4f8b\\u53c2\\u6570 \\u00b7 \\u70b9 POST /mcp/call \\u8fd0\\u884c\\u3002';"
        "document.getElementById('try').scrollIntoView({behavior:'smooth',block:'start'});"
        "}"
        "function run(){"
        "var raw=document.getElementById('argsBox').value;"
        "var body;try{body=JSON.parse(raw);}catch(e){document.getElementById('result').textContent='\\u00d7 JSON \\u89e3\\u6790\\u5931\\u8d25\\uff1a'+e.message;return;}"
        "var out=document.getElementById('result');"
        "out.textContent='\\u2192 POST /mcp/call \\u00b7 '+body.tool+' \\u00b7 ...';"
        "fetch('/mcp/call',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})"
        ".then(function(r){return r.json().then(function(j){out.textContent='\\u2190 '+r.status+' '+r.statusText+'\\n'+JSON.stringify(j,null,2);});})"
        ".catch(function(e){out.textContent='\\u00d7 fetch \\u5931\\u8d25\\uff1a'+e.message;});"
        "}"
        "document.getElementById('runBtn').addEventListener('click',run);"
        "(function(){var html=document.documentElement;var saved=localStorage.getItem('lm-theme');"
        "if(saved==='dark')html.setAttribute('data-theme','dark');"
        "else if(!saved&&matchMedia('(prefers-color-scheme:dark)').matches)html.setAttribute('data-theme','dark');"
        "var btn=document.getElementById('themeToggle');"
        "function setIcon(){btn.textContent=html.getAttribute('data-theme')==='dark'?'\\u2600':'\\u263e';}setIcon();"
        "btn.addEventListener('click',function(){var d=html.getAttribute('data-theme')==='dark';"
        "if(d){html.removeAttribute('data-theme');localStorage.setItem('lm-theme','light');}"
        "else{html.setAttribute('data-theme','dark');localStorage.setItem('lm-theme','dark');}setIcon();});})();"
        "render();"
        "if(TOOLS.length){pick(TOOLS[0].name,DEMO[TOOLS[0].name]||{});}"
        "})();"
        "</script>"
        "</body></html>"
    )


class _Handler(BaseHTTPRequestHandler):  # noqa: D401 – stdlib HTTP handler
    """Trivial JSON adapter used when the ``mcp`` package is unavailable."""

    def _json(self, status: int, payload: Any) -> None:
        body = to_json(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        # Visualization page (served at "/" too so nginx /mcp -> upstream / works)
        if self.path in ("/", "/mcp", "/mcp/", "/visual", "/index.html"):
            self._html(200, _render_visual_html())
            return
        # Raw tools listing — JSON
        if (
            self.path.startswith("/list_tools")
            or self.path.startswith("/tools")
            or self.path.startswith("/mcp/tools")
        ):
            self._json(200, {"server": "LarkMentor", "tools": list_tools()})
            return
        if self.path == "/health" or self.path == "/mcp/health":
            self._json(200, {"status": "ok", "server": "LarkMentor"})
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            self._json(400, {"error": "bad_json"})
            return
        if self.path.startswith("/call") or self.path.startswith("/mcp/call"):
            tool = body.get("tool")
            args = body.get("arguments", {}) or {}
            self._json(200, call_tool(tool, args))
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def do_OPTIONS(self) -> None:  # noqa: N802
        # CORS preflight for the visual page calling /mcp/call cross-origin
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003,N802
        return  # silence default stderr logging


def _start_fallback_http(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), _Handler)
    logger.info("LarkMentor fallback MCP HTTP server listening on http://%s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LarkMentor MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse", "http"], default="stdio",
                        help="stdio for MCP clients, sse for FastMCP, http for plain JSON")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.transport == "stdio":
        if _start_mcp_proper("stdio", args.port):
            return 0
        logger.warning("Stdio transport requires the mcp SDK; switching to HTTP")
    elif args.transport == "sse":
        if _start_mcp_proper("sse", args.port):
            return 0
        logger.warning("FastMCP unavailable; switching to plain HTTP fallback")

    _start_fallback_http(args.host, args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
