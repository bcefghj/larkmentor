"""MCP (Model Context Protocol) client.

Implements the subset of the 2025-03 MCP spec needed for Agent-Pilot:

* **JSON-RPC 2.0** over two transports:
  - **stdio**: local subprocess (e.g. `@larksuiteoapi/lark-mcp`)
  - **Streamable HTTP**: remote (e.g. `https://mcp.feishu.cn/mcp`)
* Three roles: **Host** (LarkMentor agent), **Client** (per-server
  connection), **Server** (external tool provider).
* Methods: `initialize`, `tools/list`, `tools/call`, `resources/list`,
  `resources/read`, `prompts/list`, `ping`.

Servers registered here are exposed as first-class ToolSpec entries in the
ToolRegistry: the tool name is prefixed `mcp:<server_alias>.<tool_name>`.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("pilot.harness.mcp_client")


class MCPError(Exception):
    pass


class MCPTransport:
    STDIO = "stdio"
    HTTP_STREAMABLE = "http_streamable"


@dataclass
class MCPServerConfig:
    alias: str
    transport: str
    # stdio fields
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    # http fields
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    timeout_sec: int = 30


class MCPClient:
    """A single connection to one MCP server."""

    def __init__(self, cfg: MCPServerConfig) -> None:
        self.cfg = cfg
        self._proc: Optional[subprocess.Popen] = None
        self._stdin: Any = None
        self._stdout: Any = None
        self._lock = threading.RLock()
        self._initialized = False
        self._tools: List[Dict[str, Any]] = []
        self._pending: Dict[str, Dict[str, Any]] = {}

    # ── Lifecycle ──

    def connect(self) -> bool:
        if self.cfg.transport == MCPTransport.STDIO:
            return self._connect_stdio()
        return True  # HTTP is stateless; connect happens per-call.

    def _connect_stdio(self) -> bool:
        if not self.cfg.command:
            raise MCPError(f"stdio server {self.cfg.alias} missing command")
        env = {**os.environ, **self.cfg.env}
        try:
            self._proc = subprocess.Popen(
                [self.cfg.command, *self.cfg.args],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=env, text=True, bufsize=1,
            )
            self._stdin = self._proc.stdin
            self._stdout = self._proc.stdout
            self._initialize_session()
            return True
        except FileNotFoundError:
            logger.warning("mcp stdio command not found: %s (server=%s). "
                           "Install with: npm i -g %s",
                           self.cfg.command, self.cfg.alias, self.cfg.command)
            return False
        except Exception as exc:
            logger.warning("mcp stdio connect failed %s: %s", self.cfg.alias, exc)
            return False

    def _initialize_session(self) -> None:
        result = self._rpc_call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}, "resources": {}},
            "clientInfo": {"name": "larkmentor-agent-pilot", "version": "2.0.0"},
        })
        if "error" in result:
            raise MCPError(f"initialize failed: {result['error']}")
        self._initialized = True
        try:
            tools_resp = self._rpc_call("tools/list", {})
            self._tools = (tools_resp.get("result") or {}).get("tools", []) or []
        except Exception as exc:
            logger.debug("tools/list failed on %s: %s", self.cfg.alias, exc)

    def close(self) -> None:
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    # ── RPC ──

    def _rpc_call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.cfg.transport == MCPTransport.STDIO:
            return self._rpc_stdio(method, params)
        if self.cfg.transport == MCPTransport.HTTP_STREAMABLE:
            return self._rpc_http(method, params)
        raise MCPError(f"unknown transport {self.cfg.transport}")

    def _rpc_stdio(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self._stdin or not self._stdout:
            raise MCPError("stdio not connected")
        req_id = uuid.uuid4().hex[:12]
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        line = json.dumps(payload) + "\n"
        with self._lock:
            try:
                self._stdin.write(line)
                self._stdin.flush()
            except Exception as exc:
                raise MCPError(f"stdio write failed: {exc}")
            deadline = time.time() + self.cfg.timeout_sec
            while time.time() < deadline:
                resp_line = self._stdout.readline()
                if not resp_line:
                    break
                try:
                    resp = json.loads(resp_line)
                except Exception:
                    continue
                if resp.get("id") == req_id:
                    return resp
            raise MCPError(f"stdio rpc timeout method={method}")

    def _rpc_http(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import urllib.request
            import urllib.error
        except Exception as exc:
            raise MCPError(f"urllib unavailable: {exc}")
        req_id = uuid.uuid4().hex[:12]
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", **self.cfg.headers}
        req = urllib.request.Request(self.cfg.url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_sec) as r:
                raw = r.read()
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise MCPError(f"http {exc.code}: {body[:200]}")
        except Exception as exc:
            raise MCPError(f"http rpc failed: {exc}")

    # ── High-level ──

    def list_tools(self) -> List[Dict[str, Any]]:
        if self.cfg.transport == MCPTransport.HTTP_STREAMABLE and not self._tools:
            try:
                resp = self._rpc_call("tools/list", {})
                self._tools = (resp.get("result") or {}).get("tools", []) or []
            except Exception as exc:
                logger.debug("tools/list http failed %s: %s", self.cfg.alias, exc)
        return list(self._tools)

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        resp = self._rpc_call("tools/call", {"name": name, "arguments": arguments or {}})
        if "error" in resp:
            raise MCPError(f"tools/call error: {resp['error']}")
        return resp.get("result") or {}


class MCPManager:
    """Registers many MCPClient instances and exposes them as Agent-Pilot tools."""

    def __init__(self) -> None:
        self._clients: Dict[str, MCPClient] = {}
        self._lock = threading.RLock()

    def register(self, cfg: MCPServerConfig) -> bool:
        client = MCPClient(cfg)
        ok = client.connect()
        with self._lock:
            self._clients[cfg.alias] = client
        return ok

    def client(self, alias: str) -> Optional[MCPClient]:
        with self._lock:
            return self._clients.get(alias)

    def list_aliases(self) -> List[str]:
        with self._lock:
            return sorted(self._clients.keys())

    def list_tools(self) -> List[Tuple[str, Dict[str, Any]]]:
        """Flat list of (alias, tool_spec) across all servers."""
        out: List[Tuple[str, Dict[str, Any]]] = []
        for alias, client in list(self._clients.items()):
            for t in client.list_tools():
                out.append((alias, t))
        return out

    def dispatch(self, alias: str, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        client = self.client(alias)
        if not client:
            raise MCPError(f"unknown MCP server alias: {alias}")
        return client.call_tool(tool_name, args)

    def export_as_toolspecs(self) -> List[Dict[str, Any]]:
        """Flatten into ToolSpec-like dicts usable by ToolRegistry."""
        out = []
        for alias, tspec in self.list_tools():
            qname = f"mcp:{alias}.{tspec.get('name', 'unnamed')}"
            out.append({
                "name": qname,
                "description": tspec.get("description", "") or "",
                "parameters": tspec.get("inputSchema", {}),
                "alias": alias,
                "tool_name": tspec.get("name", ""),
            })
        return out

    def close_all(self) -> None:
        with self._lock:
            for c in self._clients.values():
                try:
                    c.close()
                except Exception:
                    pass
            self._clients.clear()


def build_feishu_remote_config() -> Optional[MCPServerConfig]:
    """Official Feishu remote MCP: https://mcp.feishu.cn/mcp (December 2025)."""
    tat = os.getenv("FEISHU_MCP_TAT") or os.getenv("FEISHU_MCP_TENANT_ACCESS_TOKEN")
    uat = os.getenv("FEISHU_MCP_UAT") or os.getenv("FEISHU_MCP_USER_ACCESS_TOKEN")
    if not (tat or uat):
        return None
    headers = {}
    if tat:
        headers["X-Lark-MCP-TAT"] = tat
    if uat:
        headers["X-Lark-MCP-UAT"] = uat
    allowed = os.getenv("FEISHU_MCP_ALLOWED_TOOLS")
    if allowed:
        headers["X-Lark-MCP-Allowed-Tools"] = allowed
    return MCPServerConfig(
        alias="feishu_remote",
        transport=MCPTransport.HTTP_STREAMABLE,
        url=os.getenv("FEISHU_MCP_URL", "https://mcp.feishu.cn/mcp"),
        headers=headers,
        timeout_sec=45,
    )


def build_feishu_local_config() -> Optional[MCPServerConfig]:
    """Local `@larksuiteoapi/lark-mcp` npx server."""
    app_id = os.getenv("FEISHU_APP_ID") or os.getenv("APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET") or os.getenv("APP_SECRET")
    if not (app_id and app_secret):
        return None
    return MCPServerConfig(
        alias="feishu_local",
        transport=MCPTransport.STDIO,
        command="npx",
        args=["-y", "@larksuiteoapi/lark-mcp", "mcp", "-a", app_id, "-s", app_secret],
        env={"FEISHU_APP_ID": app_id, "FEISHU_APP_SECRET": app_secret},
        timeout_sec=30,
    )


_default: Optional[MCPManager] = None
_default_lock = threading.Lock()


def load_from_json(path: str) -> List[MCPServerConfig]:
    """Load MCP server configs from ``.larkmentor/mcp.json``.

    Schema::

        {"servers": [
            {"alias": "lark-local", "transport": "stdio",
             "command": "lark-mcp", "args": ["..."], "env_pass": ["X","Y"]},
            {"alias": "lark-remote", "transport": "http",
             "url": "...", "headers": {"Authorization": "Bearer ${X}"}}
        ]}

    ``${VAR}`` is substituted against ``os.environ`` at load time.
    """
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        logger.warning("mcp.json parse failed %s: %s", path, exc)
        return []

    def _subst(v: Any) -> Any:
        if isinstance(v, str):
            out = v
            for key, val in os.environ.items():
                out = out.replace("${" + key + "}", val)
            return out
        if isinstance(v, dict):
            return {k: _subst(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_subst(x) for x in v]
        return v

    servers = _subst(data.get("servers") or [])
    cfgs: List[MCPServerConfig] = []
    for s in servers:
        alias = s.get("alias") or ""
        if not alias:
            continue
        transport = s.get("transport") or "stdio"
        if transport == "stdio":
            env = {k: os.environ.get(k, "") for k in (s.get("env_pass") or [])}
            cfgs.append(MCPServerConfig(
                alias=alias,
                transport=MCPTransport.STDIO,
                command=s.get("command"),
                args=list(s.get("args") or []),
                env=env,
                timeout_sec=int(s.get("timeout_sec") or 30),
            ))
        elif transport == "http":
            cfgs.append(MCPServerConfig(
                alias=alias,
                transport=MCPTransport.HTTP_STREAMABLE,
                url=s.get("url"),
                headers=dict(s.get("headers") or {}),
                timeout_sec=int(s.get("timeout_sec") or 45),
            ))
    return cfgs


def default_mcp_manager() -> MCPManager:
    global _default
    with _default_lock:
        if _default is None:
            mgr = MCPManager()
            remote = build_feishu_remote_config()
            if remote:
                ok = mgr.register(remote)
                logger.info("feishu remote MCP registered: %s", ok)
            local = build_feishu_local_config()
            if local:
                ok = mgr.register(local)
                logger.info("feishu local MCP registered: %s", ok)
            root = os.getenv("LARKMENTOR_ROOT", os.getcwd())
            extra = load_from_json(os.path.join(root, ".larkmentor", "mcp.json"))
            for cfg in extra:
                ok = mgr.register(cfg)
                logger.info("mcp.json server %s registered: %s", cfg.alias, ok)
            _default = mgr
        return _default
