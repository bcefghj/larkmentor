# Agent-Pilot × 飞书生态集成说明

## 1. WebSocket 长连接模式（推荐）

Agent-Pilot 使用飞书官方推荐的 **WebSocket 长连接模式** 接收事件回调，无需公网 IP、域名或 HTTPS 证书。

```python
# main.py 中的关键配置
from lark_oapi.adapter.websocket import LarkWebSocketClient

ws_client = LarkWebSocketClient.builder(Config.FEISHU_APP_ID, Config.FEISHU_APP_SECRET)
    .event_handler(lark_event_handler)
    .callback_handler(lark_card_handler)
    .build()
ws_client.start()
```

优势：
- 本地开发即可接收飞书事件，无需内网穿透
- 连接稳定，自动重连
- 飞书官方 2026 年 4 月公告推荐方案

## 2. 飞书 CLI 集成（24 Skills / 200+ 命令）

Agent-Pilot 集成了飞书 CLI 工具，通过 `core/feishu_cli/` 模块提供 24 个 Skill 覆盖 17+ 业务域：

| Skill | 说明 | 典型命令 |
|-------|------|---------|
| lark-im | 消息与群组 | `lark-cli im send --chat-id {id} --text {text}` |
| lark-doc / lark-docx | 云文档 | `lark-cli docx create --title {title}` |
| lark-slides | 演示稿 | `lark-cli slides create --title {title}` |
| lark-base / lark-bitable | 多维表格 | `lark-cli base list-records --app-token {token}` |
| lark-calendar | 日历 | `lark-cli calendar list-events --start {start}` |
| lark-drive | 云空间 | `lark-cli drive upload --file {path}` |
| lark-wiki | 知识库 | `lark-cli wiki search --query {query}` |
| lark-board | 白板 | `lark-cli board create --title {title}` |
| lark-search | 全局搜索 | `lark-cli search universal --query {query}` |
| ... | 其他 15 个 Skill | 见 `core/feishu_cli/mcp_config.py` |

### 使用方式

```bash
# 检查 CLI 可用性
python -c "from core.feishu_cli import is_cli_available; print(is_cli_available())"

# 列出所有 Skill
python -c "from core.feishu_cli import list_skill_names; print(list_skill_names())"
```

## 3. MCP 协议集成

Agent-Pilot 通过 MCP (Model Context Protocol) 协议与飞书 OpenAPI 对接：

```json
{
  "name": "lark-openapi",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@anthropic-ai/mcp-proxy", "--", "lark-openapi-mcp"]
}
```

自研 MCP Server 位于 `core/mcp_server/`，提供 21 个内建工具 + 24 个飞书 CLI Skills。

## 4. 飞书 aily 任务模式的借鉴

Agent-Pilot 的设计理念与飞书 aily「任务模式」高度对齐：

| 飞书 aily 特性 | Agent-Pilot 对应实现 |
|---------------|-------------------|
| 从对话理解任务 | 三闸门 IntentDetector（规则 + LLM + 最小信息校验） |
| 拆解执行计划 | DAG 编排引擎 + 5 推理模式自动选择 |
| 调用飞书能力完成工作 | 飞书 API SDK + CLI 24 Skills + MCP 协议 |
| 多步骤编排 | PilotPlanner → PilotOrchestrator 并行分组执行 |
| 结果交付 | 流式打字机卡片 + 飞书 Docx/Slides 分享链接 |

Agent-Pilot 在 aily 基础上增加了：
- **主动任务发现**：无需 @Bot，从自然对话中主动识别任务意图
- **多 Agent 协同**：5 命名 Agent 分工验证，Builder-Validator 严格分离
- **学习闭环**：3 次相似任务自动生成 SKILL.md，第 4 次跳过 60% 规划
- **多端 CRDT 同步**：Yjs y-py 实现真正的无冲突多端实时同步

## 5. 飞书 API 接入清单

| API | 用途 | 模块 |
|-----|------|------|
| IM 消息 | 接收/发送消息、卡片 | `bot/message_sender.py` |
| Docx 文档 | 创建/编辑飞书文档 | `core/agent_pilot/tools/doc_tool.py` |
| Bitable 多维表格 | 结构化数据存储/分析 | `core/feishu_workspace_init.py` |
| Calendar 日历 | 日程查询、专注模式 | `core/schedule_manager.py` |
| Wiki 知识库 | Mentor 知识检索 | `core/mentor/knowledge_base.py` |
| 妙记 Minutes | 会议纪要提取 | `core/feishu_cli/` |
| Reaction 表情 | 消息反馈标记 | `bot/handlers/shield.py` |
| WebSocket | 事件订阅长连接 | `main.py` |
