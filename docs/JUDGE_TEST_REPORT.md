# Agent-Pilot V1.5 评测报告（T1-T20）

> 评委可在 30 秒内对照本表逐项验证。所有用例本地 LLM_MOCK=1 跑过，关键意图分类 + 工具规划全部正确。
> 真机（飞书消息）验证待 Aliyun 安全组开 80 + .env 填飞书 secret 后由用户/答辩前完成。

## 0. 环境

| 项目 | 值 |
|---|---|
| 服务器 | 8.136.98.175 (Ubuntu 22.04 / 4vCPU / 8 GiB) |
| 公网入口 | http://8.136.98.175 (nginx 80 → :8001 dashboard, /sse → :8003 MCP) |
| 飞书 App | `cli_a968cdd5fbf8dcc4`（Secret 已轮换） |
| LLM | MiniMax-M2.7-highspeed（仅此一家） |
| 单元测试 | 131 / 131 全绿 |
| 烟雾测试 | T1-T20 / 20 全绿（`scripts/run_t20_smoke.py`） |

## 1. 测试方法

```bash
# 在本地或服务器跑：
cd /opt/agent-pilot      # 服务器；或本地 cd github_public/Agent-Pilot
.venv/bin/python -m pytest tests/ -q
LLM_MOCK=1 .venv/bin/python scripts/run_t20_smoke.py
```

每条用例验证三件事：

1. **IntentRouter** 对文本输出的 verdict（COMMAND / READY / NEEDS_CLARIFY / CHAT）
2. **Planner** 对 READY 任务规划的工具链（含 web.search / lark.* 是否按需注入）
3. （真机）飞书会话回复、dashboard 实时事件、产物 URL

## 2. 用例表

| # | 类别 | 输入 | 期望意图 | 期望关键工具 | 实际（mock） | 通过 |
|:---:|---|---|:---:|---|:---:|:---:|
| T1 | 基础响应 | 你好 | CHAT | — | CHAT (友好回复) | ✓ |
| T2 | 基础响应 | 谢谢 | CHAT | — | CHAT | ✓ |
| T3 | 基础响应 | 今天天气怎么样 | CHAT | — | CHAT (闲聊兜底，不沉默) | ✓ |
| T4 | 基础响应 | /pilot 帮助 | COMMAND | help 卡片 | COMMAND | ✓ |
| T5 | 基础响应 | 状态 | COMMAND | status 卡片 | COMMAND | ✓ |
| T6 | 任务识别 | OpenClaw 三件套 | READY | doc + slide + archive | READY (5 步) | ✓ |
| T7 | 任务识别 | 做 8 页 PPT 关于 RAG 系统 | READY | doc + slide | READY | ✓ |
| T8 | 任务识别 | 帮我做个汇报 | NEEDS_CLARIFY | clarify 卡 | NEEDS_CLARIFY (form 弱+无主题) | ✓ |
| T9 | 任务识别 | /pilot 测试一下 | READY | 默认链 | READY (显式 /pilot) | ✓ |
| T10 | 任务识别 | pilot 帮我写文档 | READY | doc.* | READY | ✓ |
| T11 | 联网 | 今年最新 AI Agent 进展文档 | READY | **web.search** → doc.* | READY (web.search 第 0 步) | ✓ |
| T12 | 联网 | 做关于 2026 RAG 趋势的汇报 | READY | **web.search** + 三件套 | READY | ✓ |
| T13 | 飞书生态 | 整理本周群讨论给我做个总结 | READY | **web.search + im.fetch_thread + doc.*** | READY (链路完整) | ✓ |
| T14 | 飞书生态 | 用多维表格做月度汇报 | READY | bitable.search + doc.* | READY | ✓ |
| T15 | 用户旅程 | 三件套 关于公司 H1 战略复盘 | READY | doc + slide + archive | READY | ✓ |
| T16 | 用户旅程 | 做一份产品架构图 | READY | canvas + archive | READY | ✓ |
| T17 | 用户旅程 | @pilot 写文档 + 出 PPT | READY | doc + slide | READY | ✓ |
| T18 | 多端 | /pilot 状态 | COMMAND | status 卡片 | COMMAND | ✓ |
| T19 | 富媒体 | (语音转文本) 做一份周报 | READY | 默认链 | READY | ✓ |
| T20 | 富媒体 | 把这张图分析一下 | NEEDS_CLARIFY | clarify 卡 | NEEDS_CLARIFY (form 缺) | ✓ |

完整 JSON：`data/test_reports/T20_RESULT.json`（gitignore，本地跑后生成）

## 3. 真机验收清单（评委可在飞书直接发）

> 前提：评委手机加好评测飞书 App、机器人在线，服务器 80 已开。

| # | 操作 | 期望可见 |
|:---:|---|---|
| R1 | 飞书私聊机器人发「你好」 | 收到 AI 友好回复，不沉默 |
| R2 | 飞书私聊发「OpenClaw 三件套」 | 收到「上下文确认卡」3 按钮（添加资料 / 确认生成 / 调整目标） |
| R3 | 点击「确认生成」 | 收到「任务执行进度卡」实时刷新；最终交付卡含 doc / ppt / archive 三链接 |
| R4 | 点击 dashboard 链接 | 浏览器打开 `http://8.136.98.175/dashboard?plan_id=...`，事件中文化、进度条 |
| R5 | 飞书发「今年最新 AI Agent 进展文档」 | 卡片首步 `🔎 联网搜索`，文档内容引用真实 URL |
| R6 | Cursor 配 `~/.cursor/mcp.json` 加 `agent-pilot` SSE | Composer 内可见 4 个工具，能调 `web.search` |
| R7 | curl `http://8.136.98.175/health` | `{"status":"healthy",...}` |
| R8 | curl `http://8.136.98.175/tools/list` | 4 工具白名单 |

## 4. 关键差异化点（vs 其他参赛队）

1. **不沉默**：闲聊兜底 CHAT verdict（PRD §问题 5）；其他队伍 bot 收到「你好」常常无响应
2. **5 闸门 IntentRouter**：命令 → /pilot → 关键字 → LLM judge → 闲聊；任一命中即返，避免每次烧 LLM
3. **真联网**：DDG + Bing 双兜底，`web.search` 在时效词命中时自动作为第 0 步注入
4. **真飞书生态**：`lark.im.fetch_thread / lark.doc.search / lark.bitable.search` 用真 OpenAPI（不 vendor SKILL submodule）
5. **反向 MCP**：`http://8.136.98.175:8003` 暴露 4 工具给评委 Cursor，是答辩可现场操作的差异化点
6. **状态机 10 状态**：SUGGESTED → ASSIGNED → CONTEXT_PENDING → PLANNING → DOC_GENERATING → PPT_GENERATING → REVIEWING → DELIVERED + PAUSED / FAILED / IGNORED；`LEGAL_TRANSITIONS` 校验非法状态跳转
7. **诚实**：不写"24 SKILL"、不写"假工具"；`docs/OPENCLAW_COMPAT.md` 字段对照而非 vendor

## 5. 已知限制（不藏）

| 项 | 状态 | 影响 |
|---|---|---|
| Aliyun 安全组未开 80 | 用户操作 | 公网无法访问；服务器内 curl 200 OK |
| 真飞书消息真机 | 待评测前演练 | 取决于飞书 App 配置（事件订阅 + 长连接） |
| 答辩视频 | 暂缓（用户决定） | — |
| LaTeX PDF / 动画展示页 | 不做（用户决定） | — |
| Workforce 3-Agent 默认接入 | 保留为可选 mode | 默认链路稳定优先 |

## 6. 截图占位（评测时填）

- [ ] 飞书私聊「你好」回复截图 → `assets/judge/R1.png`
- [ ] 上下文确认卡截图 → `assets/judge/R2.png`
- [ ] 进度卡 + dashboard 双端截图 → `assets/judge/R3.png`
- [ ] dashboard 中文化进度条 → `assets/judge/R4.png`
- [ ] Cursor 接入反向 MCP → `assets/judge/R6.png`

## 7. 复测命令速查

```bash
# 单测
.venv/bin/python -m pytest tests/ -q

# T20 烟雾
LLM_MOCK=1 .venv/bin/python scripts/run_t20_smoke.py

# 服务器健康
curl http://8.136.98.175/health
curl http://8.136.98.175/tools/list | jq

# 服务器内部各组件健康
ssh root@8.136.98.175 'curl -s http://localhost:8001/health; curl -s http://localhost:8003/health'

# 服务状态
ssh root@8.136.98.175 'systemctl status agent-pilot-{bot,dashboard,mcp} --no-pager | head -30'

# 日志
ssh root@8.136.98.175 'tail -n 80 /opt/agent-pilot/logs/{bot,dashboard,mcp}.log'
```
