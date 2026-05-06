# Agent-Pilot 反向 MCP Server 接入指南

Agent-Pilot V1.5 内置一个 HTTP+SSE 反向 MCP Server（`pilot/surface/lark_mcp_runner.py`），监听 `:8003`，把核心工具暴露给外部 AI client（Cursor / Claude Desktop / Trae）。

> 这是答辩差异化点：评委可以在自己的 Cursor 里直接调用我们部署在云上的 V1.5 工具。

## 1. 启动

服务器（生产）：

```bash
sudo systemctl start agent-pilot-mcp
sudo systemctl enable agent-pilot-mcp
```

本地开发：

```bash
cd github_public/Agent-Pilot
python -c "from pilot.surface.lark_mcp_runner import run; run()"
```

## 2. 健康检查

```bash
curl http://8.136.98.175:8003/health
# {"status":"healthy","ts":...}

curl http://8.136.98.175:8003/
# {"name":"Agent-Pilot V1.5 MCP Server","exposed_tools":["doc.create","doc.append","slide.generate","web.search"], ...}

curl http://8.136.98.175:8003/tools/list | jq
```

## 3. 暴露的工具

只暴露 4 个非破坏性工具，避免外部 client 误调毁灭性操作：

| 工具 | 用途 |
|---|---|
| `doc.create` | 创建飞书 Docx 文档 |
| `doc.append` | 向 Docx 追加 LLM 自动生成的 Markdown |
| `slide.generate` | 生成 .pptx + Slidev md + 演讲稿 |
| `web.search` | DDG + Bing 联网搜索 |

## 4. 在 Cursor 接入

编辑 `~/.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "agent-pilot": {
      "url": "http://8.136.98.175:8003/sse"
    }
  }
}
```

重启 Cursor，命令面板搜索 `MCP: Refresh Servers`，就能在 Composer 里看到 4 个工具。

## 5. 在 Claude Desktop 接入

`~/Library/Application Support/Claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "agent-pilot": {
      "url": "http://8.136.98.175:8003/sse"
    }
  }
}
```

> 若 Claude Desktop 仍只支持 stdio，可用 `mcp-proxy` 把 SSE 转成 stdio：
>
> ```bash
> npm i -g @modelcontextprotocol/mcp-proxy
> mcp-proxy http://8.136.98.175:8003/sse
> ```

## 6. 直接 HTTP 调用（绕过 MCP client）

```bash
curl -X POST http://8.136.98.175:8003/tools/call \
  -H 'Content-Type: application/json' \
  -d '{"name":"web.search","arguments":{"query":"Agent-Pilot 飞书","k":5}}'
```

## 7. 协议说明

- `GET /sse`：建立 SSE 长连接，server 每 15s emit `event: ping`，连接断开自动结束
- `POST /messages`：JSON-RPC 2.0 子集，支持 `tools/list` / `tools/call`
- `GET /tools/list`：直接返回工具清单（非 MCP 协议，方便 curl 调试）
- `POST /tools/call`：白名单工具直接调用

> 这里不是 MCP 完整协议（如 prompts、resources、samplers）。Cursor 1.x 用 streamable HTTP，
> 后续可在 `lark_mcp_runner.py` 里平滑升级，无需改 client 配置。

## 8. 安全

- nginx 反代 `/sse/` → `127.0.0.1:8003`，UFW 不暴露 8003 公网
- 反向 MCP 默认无鉴权（演示用）；生产部署可在 nginx 加 Basic Auth 或 IP 白名单

## 9. 常见问题

**Q：为什么只暴露 4 个工具？**
A：archive.bundle 等会写文件、slide.rehearse 会触发 LLM 长任务，不适合外部 client 任意触发。后续可加细粒度授权。

**Q：和 飞书 OpenAPI MCP 是同一个吗？**
A：不是。飞书官方 `larksuite/lark-openapi-mcp` 是把飞书 OpenAPI 暴露给 AI；
我们这个是把 Agent-Pilot 的工具反向暴露给 AI。两者方向相反、独立部署。
