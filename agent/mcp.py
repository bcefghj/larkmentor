"""MCP Manager · 三通道（stdio + HTTP Streamable + CLI Skills）

对齐 Claude Code MCP architecture。

三种 transport：
1. stdio：subprocess.Popen（@larksuiteoapi/lark-mcp 本地）
2. HTTP Streamable：requests + SSE（mcp.feishu.cn/mcp 远程）
3. cli：Feishu CLI Skills（22 个飞书能力域，subprocess 调用）

JSON-RPC 2.0 协议。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent.mcp")


@dataclass
class MCPServer:
    alias: str
    transport: str  # "stdio" | "http"
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True


class StdioClient:
    def __init__(self, server: MCPServer) -> None:
        self.server = server
        self.proc: Optional[subprocess.Popen] = None
        self.tools: List[Dict] = []
        self._lock = threading.Lock()
        self._msg_id = 0

    def start(self) -> bool:
        if not self.server.command:
            logger.error("stdio %s: no command", self.server.alias)
            return False
        env = os.environ.copy()
        for k, v in self.server.env.items():
            env[k] = os.path.expandvars(v)
        cmd_expanded = [os.path.expandvars(a) for a in [self.server.command, *self.server.args]]
        try:
            self.proc = subprocess.Popen(
                cmd_expanded,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                bufsize=1,
            )
            logger.info("stdio %s started: pid=%s", self.server.alias, self.proc.pid)
            # Initialize
            self._initialize()
            self._list_tools()
            return True
        except FileNotFoundError as e:
            logger.warning("stdio %s command not found: %s (tool will be unavailable)", self.server.alias, e)
            return False
        except Exception as e:
            logger.warning("stdio %s start failed: %s", self.server.alias, e)
            return False

    def _send(self, method: str, params: Dict) -> Optional[Dict]:
        if not self.proc or self.proc.poll() is not None:
            return None
        with self._lock:
            self._msg_id += 1
            req = {"jsonrpc": "2.0", "id": self._msg_id, "method": method, "params": params}
            try:
                self.proc.stdin.write(json.dumps(req) + "\n")
                self.proc.stdin.flush()
                line = self.proc.stdout.readline()
                if not line:
                    return None
                return json.loads(line)
            except Exception as e:
                logger.warning("stdio %s send failed: %s", self.server.alias, e)
                return None

    def _initialize(self) -> None:
        self._send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "agent-pilot-v4", "version": "4.0.0"},
                "capabilities": {},
            },
        )

    def _list_tools(self) -> None:
        resp = self._send("tools/list", {})
        if resp and "result" in resp:
            self.tools = resp["result"].get("tools", [])
            logger.info("stdio %s: %d tools listed", self.server.alias, len(self.tools))

    def call(self, tool_name: str, arguments: Dict) -> Optional[Dict]:
        resp = self._send("tools/call", {"name": tool_name, "arguments": arguments})
        if resp and "result" in resp:
            return resp["result"]
        return None

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()


class HttpClient:
    def __init__(self, server: MCPServer) -> None:
        self.server = server
        self.tools: List[Dict] = []
        self._lock = threading.Lock()
        self._msg_id = 0

    def start(self) -> bool:
        if not self.server.url:
            return False
        # Just list tools (stateless for HTTP streamable)
        try:
            import requests  # noqa

            self._list_tools()
            return True
        except ImportError:
            logger.warning("requests not installed, HTTP MCP %s unavailable", self.server.alias)
            return False
        except Exception as e:
            logger.warning("http %s start failed: %s", self.server.alias, e)
            return False

    def _send(self, method: str, params: Dict) -> Optional[Dict]:
        try:
            import requests
        except ImportError:
            return None
        with self._lock:
            self._msg_id += 1
            req = {"jsonrpc": "2.0", "id": self._msg_id, "method": method, "params": params}
            headers = {"Content-Type": "application/json"}
            for k, v in self.server.headers.items():
                headers[k] = os.path.expandvars(v)
            try:
                r = requests.post(self.server.url, json=req, headers=headers, timeout=15)
                if r.status_code != 200:
                    return None
                return r.json()
            except Exception as e:
                logger.debug("http %s send failed: %s", self.server.alias, e)
                return None

    def _list_tools(self) -> None:
        resp = self._send("tools/list", {})
        if resp and "result" in resp:
            self.tools = resp["result"].get("tools", [])

    def call(self, tool_name: str, arguments: Dict) -> Optional[Dict]:
        resp = self._send("tools/call", {"name": tool_name, "arguments": arguments})
        if resp and "result" in resp:
            return resp["result"]
        return None

    def stop(self) -> None:
        pass


class FeishuCLIClient:
    """Client for Feishu CLI Skills — wraps subprocess calls with skill metadata."""

    def __init__(self) -> None:
        self.tools: List[Dict] = []
        self._skills: Dict[str, Dict[str, Any]] = {}

    def start(self) -> bool:
        try:
            from core.feishu_cli.mcp_config import (
                FEISHU_CLI_SKILLS,
                is_cli_available,
            )

            if not is_cli_available():
                logger.info("Feishu CLI not found in PATH, skills loaded as metadata-only")

            self._skills = FEISHU_CLI_SKILLS
            self.tools = [
                {
                    "name": f"cli.{skill_id}",
                    "description": skill["description"],
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "command_index": {
                                "type": "integer",
                                "description": f"Command index (0-{len(skill['commands'])-1})",
                                "default": 0,
                            },
                            "params": {
                                "type": "object",
                                "description": "Parameters to substitute into the command template",
                            },
                        },
                    },
                }
                for skill_id, skill in self._skills.items()
            ]
            logger.info("FeishuCLIClient: %d skills, %d total commands",
                         len(self._skills),
                         sum(len(s["commands"]) for s in self._skills.values()))
            return True
        except Exception as e:
            logger.warning("FeishuCLIClient start failed: %s", e)
            return False

    def call(self, tool_name: str, arguments: Dict) -> Optional[Dict]:
        skill_id = tool_name.replace("cli.", "", 1)
        skill = self._skills.get(skill_id)
        if not skill:
            return {"error": True, "message": f"Unknown CLI skill: {skill_id}"}

        cmd_index = arguments.get("command_index", 0)
        params = arguments.get("params", {})
        commands = skill["commands"]

        if cmd_index < 0 or cmd_index >= len(commands):
            return {
                "error": True,
                "message": f"command_index {cmd_index} out of range (0-{len(commands)-1})",
            }

        try:
            from core.feishu_cli.mcp_config import run_cli_command

            return run_cli_command(commands[cmd_index], params)
        except Exception as e:
            return {"error": True, "message": str(e)}

    def stop(self) -> None:
        pass


class MCPManager:
    def __init__(self) -> None:
        self.clients: Dict[str, Any] = {}
        self.servers: List[MCPServer] = []
        self._cli_client: Optional[FeishuCLIClient] = None
        self._started = False

    def load_config(self) -> None:
        """Load from .agent-pilot/mcp.json (or environment defaults)."""
        cfg_path = Path.cwd() / ".agent-pilot" / "mcp.json"
        if not cfg_path.exists():
            cfg_path = Path.home() / ".agent-pilot" / "mcp.json"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text())
                for s in cfg.get("servers", []):
                    self.servers.append(
                        MCPServer(
                            alias=s["alias"],
                            transport=s.get("transport", "stdio"),
                            command=s.get("command"),
                            args=s.get("args", []),
                            env={k: os.getenv(k, "") for k in s.get("env_pass", [])} | s.get("env", {}),
                            url=s.get("url"),
                            headers=s.get("headers", {}),
                            enabled=s.get("enabled", True),
                        )
                    )
                logger.info("MCP config loaded: %d servers", len(self.servers))
                return
            except Exception as e:
                logger.warning("mcp.json parse failed: %s", e)
        # Defaults
        app_id = os.getenv("FEISHU_APP_ID", "")
        app_secret = os.getenv("FEISHU_APP_SECRET", "")
        if app_id and app_secret:
            self.servers.append(
                MCPServer(
                    alias="lark-local",
                    transport="stdio",
                    command="npx",
                    args=[
                        "-y",
                        "@larksuiteoapi/lark-mcp",
                        "mcp",
                        "-a",
                        app_id,
                        "-s",
                        app_secret,
                        "-t",
                        "preset.default,preset.im.default,preset.doc.default,preset.calendar.default,preset.base.default",
                    ],
                )
            )
        tat = os.getenv("FEISHU_MCP_TAT", "")
        if tat:
            self.servers.append(
                MCPServer(
                    alias="lark-remote",
                    transport="http",
                    url="https://mcp.feishu.cn/mcp",
                    headers={"Authorization": f"Bearer {tat}"},
                )
            )

    def _init_cli_client(self) -> None:
        """Initialize the Feishu CLI skills client."""
        cli = FeishuCLIClient()
        if cli.start():
            self._cli_client = cli
            self.clients["feishu-cli"] = cli
            logger.info("Feishu CLI client active with %d tools", len(cli.tools))

    def start(self) -> None:
        if self._started:
            return
        if not self.servers:
            self.load_config()

        for s in self.servers:
            if not s.enabled:
                continue
            if s.transport == "stdio":
                client = StdioClient(s)
            elif s.transport == "http":
                client = HttpClient(s)
            else:
                logger.warning("unknown transport: %s", s.transport)
                continue
            if client.start():
                self.clients[s.alias] = client

        self._init_cli_client()

        self._started = True
        logger.info("MCPManager started: %d/%d clients active (cli=%s)",
                     len(self.clients), len(self.servers) + 1,
                     "yes" if self._cli_client else "no")

    def stop(self) -> None:
        for c in self.clients.values():
            try:
                c.stop()
            except Exception as e:
                logger.debug("MCP client stop failed: %s", e)
        self.clients.clear()
        self._cli_client = None
        self._started = False

    def list_all_tools(self) -> Dict[str, List[Dict]]:
        out: Dict[str, List[Dict]] = {}
        for alias, client in self.clients.items():
            out[alias] = client.tools
        return out

    def call(self, alias: str, tool_name: str, arguments: Dict) -> Optional[Dict]:
        client = self.clients.get(alias)
        if not client:
            return None
        return client.call(tool_name, arguments)

    def call_cli_skill(self, skill_id: str, command_index: int = 0, params: Optional[Dict[str, str]] = None) -> Optional[Dict]:
        """Convenience method to call a Feishu CLI skill directly."""
        if not self._cli_client:
            return {"error": True, "message": "Feishu CLI client not initialized"}
        return self._cli_client.call(f"cli.{skill_id}", {
            "command_index": command_index,
            "params": params or {},
        })

    def get_cli_skills(self) -> Dict[str, Dict[str, Any]]:
        """Return all available Feishu CLI skill definitions."""
        if not self._cli_client:
            return {}
        return self._cli_client._skills

    def snapshot(self) -> Dict[str, Any]:
        return {
            "started": self._started,
            "cli_available": self._cli_client is not None,
            "cli_skills_count": len(self._cli_client._skills) if self._cli_client else 0,
            "servers": [
                {
                    "alias": s.alias,
                    "transport": s.transport,
                    "enabled": s.enabled,
                    "url": s.url,
                    "command": s.command,
                    "connected": s.alias in self.clients,
                    "tools": len(self.clients.get(s.alias).tools) if s.alias in self.clients else 0,
                }
                for s in self.servers
            ],
        }


_singleton: Optional[MCPManager] = None


def default_mcp_manager() -> MCPManager:
    global _singleton
    if _singleton is None:
        _singleton = MCPManager()
    return _singleton


def register_feishu_mcp() -> None:
    """Register both the MCP server (lark-openapi) and Feishu CLI skills."""
    mgr = default_mcp_manager()

    try:
        from core.feishu_cli.mcp_config import (
            FEISHU_CLI_SKILLS,
            MCP_SERVER_CONFIG,
            is_cli_available,
            is_mcp_available,
        )

        if is_mcp_available():
            logger.info("Feishu MCP server available, %d CLI skills", len(FEISHU_CLI_SKILLS))
            mgr.servers.append(
                MCPServer(
                    alias=MCP_SERVER_CONFIG["name"],
                    transport=MCP_SERVER_CONFIG["transport"],
                    command=MCP_SERVER_CONFIG["command"],
                    args=MCP_SERVER_CONFIG["args"],
                    env=MCP_SERVER_CONFIG.get("env", {}),
                )
            )

        if is_cli_available():
            logger.info("Feishu CLI available, %d skills registered", len(FEISHU_CLI_SKILLS))
        else:
            logger.info("Feishu CLI not in PATH; %d skills registered as metadata", len(FEISHU_CLI_SKILLS))

    except Exception as e:
        logger.debug("Feishu MCP not available: %s", e)
