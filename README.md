# Agent-Pilot V2.0 — Multi-Agent Pipeline 驱动的 IM 协同办公助手

> **从 IM 对话到演示稿的一键智能闭环** — 在飞书 IM 中通过自然语言触发，6 个专业 AI Agent（Intent / Planner / Research / Writer / Review / Builder）协作完成从需求理解到文档 / PPT / 画布交付的全链路自动化。

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-V2.0-orange.svg)]()
[![PRD Tests](https://img.shields.io/badge/PRD_Tests-14%2F14_PASS-brightgreen.svg)]()
[![Agents](https://img.shields.io/badge/Agents-6_专业分工-purple.svg)]()
[![Demo](https://img.shields.io/badge/Live_Demo-在线体验-blue.svg)](http://8.136.98.175)
[![PDF](https://img.shields.io/badge/技术白皮书-50页PDF-red.svg)](http://8.136.98.175/agent_pilot_report.pdf)
[![Last Commit](https://img.shields.io/github/last-commit/bcefghj/Agent-Pilot.svg)](https://github.com/bcefghj/Agent-Pilot/commits/main)

---

## 在线体验

| 入口 | 链接 | 说明 |
|------|------|------|
| **产品介绍** | [http://8.136.98.175](http://8.136.98.175) | 产品全景介绍 · 动画演示 · 技术亮点 |
| **Live Demo** | [http://8.136.98.175/demo.html](http://8.136.98.175/demo.html) | 独立全屏对话体验，与真实后端交互 |
| **Dashboard** | [http://8.136.98.175/dashboard](http://8.136.98.175/dashboard) | 实时 Agent 协作过程可视化 |
| **技术白皮书** | [http://8.136.98.175/agent_pilot_report.pdf](http://8.136.98.175/agent_pilot_report.pdf) | 50 页 A4 技术文档 |
| **MCP Server** | `http://8.136.98.175/sse` | Cursor / Claude Desktop 接入 |
| **GitHub** | [github.com/bcefghj/Agent-Pilot](https://github.com/bcefghj/Agent-Pilot) | 完整源码（185 文件，MIT 开源） |

---

## 比赛题目完成情况

> 赛道：基于 IM 的办公协同智能助手（公开版）
> 命题：Agent-Pilot · 从 IM 对话到演示稿的一键智能闭环

### Must-have 必须完成项

| 场景 | PRD 要求 | Agent-Pilot 实现 | 测试结果 |
|------|----------|-----------------|----------|
| **A: 意图入口** | IM 群聊/单聊，文本/语音触发 | IntentAgent 自然语言分类（ready/chat/clarify），支持飞书单聊 | ✅ PASS |
| **B: 任务规划** | LLM/Planner 拆解为子任务 | PlannerAgent LLM few-shot 生成 5-10 章结构化大纲 | ✅ PASS（7 章） |
| **C: 文档生成** | 自动生成并迭代文档 | WriterAgent 按章撰写 + ReviewAgent 5 维度自评迭代（最多 3 轮） | ✅ PASS（5646 字） |
| **D: PPT 生成** | 结构化演示材料 | BuilderAgent + python-pptx 生成 .pptx + speaker notes | ✅ PASS（8 页） |
| **E: 多端协同** | 移动端+桌面端实时同步 | Dashboard SSE + Flutter + WebSocket SyncHub | ✅ PASS |
| **F: 总结交付** | 汇报/归档成果 | task_delivered_card（摘要+耗时+产物链接+操作按钮） | ✅ PASS |

### Good-to-have 可选加分项

| 加分项 | Agent-Pilot 实现 | 状态 |
|--------|-----------------|------|
| **高级 Agent 能力：主动澄清** | IntentAgent 识别模糊意图 → 发送澄清卡片引导用户 | ✅ 已实现 |
| **第三方平台集成** | 深度集成飞书开放平台（Doc API / Drive API / CardKit / WebSocket Bot） | ✅ 已实现 |
| **富媒体操作** | 文档中自动插入搜索数据、表格、结构化内容 | ✅ 已实现 |
| **反向 MCP** | 暴露工具供 Cursor/Claude Desktop 调用 | ✅ 已实现 |

### 验收要求对照

| 验收要求 | 满足方式 |
|----------|----------|
| 多端协同 | 飞书 IM（移动/桌面）+ Web Dashboard + Flutter 客户端，SSE 实时同步 |
| Agent 驱动主流程 | 用户一句自然语言 → IntentAgent 自动路由到对应 Pipeline → 全链路自动执行 |
| Office 套件覆盖 | IM（飞书 Bot）+ 文档（Doc API）+ PPT（python-pptx）三套件全串联 |

---

## 效果对比

| 维度 | 传统方式 | Agent-Pilot | 提升幅度 |
|------|----------|-------------|----------|
| 写一份研究报告 | 搜索+整理+撰写 **2-4 小时** | 一句话触发，**90 秒**自动完成 | ⬆️ 96% 时间节省 |
| 做 8 页 PPT | 大纲+内容+排版 **3-5 小时** | 一句话触发，**120 秒**自动生成 | ⬆️ 97% 时间节省 |
| 应用切换 | IM → 浏览器 → 文档 → PPT → 邮件，**5+ 次** | **0 次**，全在飞书内完成 | ⬆️ 100% 消除 |
| 质量保障 | 靠个人经验 | ReviewAgent 5 维度自评 + 最多 3 轮迭代 | ⬆️ 系统性保障 |
| 多端同步 | 手动复制粘贴 | SSE + WebSocket 实时自动同步 | ⬆️ 100% 消除人工 |

---

## 架构总览

```mermaid
flowchart LR
    User["👤 用户\n飞书 IM 发消息"]
    Intent["🎯 IntentAgent\n意图识别 · 任务分类"]
    Planner["📋 PlannerAgent\n结构化大纲 · few-shot"]
    Research["🔍 ResearchAgent\nMiniMax tool calling\n联网搜索"]
    Writer["✍️ WriterAgent\n章节撰写 · 数据融合"]
    Review["🔄 ReviewAgent\n自评迭代 · 质量审核"]
    Builder["📦 BuilderAgent\n飞书 Doc · PPTX · 画布"]

    User --> Intent --> Planner --> Research --> Writer
    Writer --> Review
    Review -->|"不通过 · feedback 注入"| Writer
    Review -->|"通过"| Builder
    Builder --> Deliver["🚀 飞书 Doc / PPT / 画布"]

    style User fill:#e8f4fd,stroke:#1890ff
    style Intent fill:#fff7e6,stroke:#fa8c16
    style Planner fill:#fff7e6,stroke:#fa8c16
    style Research fill:#f6ffed,stroke:#52c41a
    style Writer fill:#f6ffed,stroke:#52c41a
    style Review fill:#fff1f0,stroke:#f5222d
    style Builder fill:#f9f0ff,stroke:#722ed1
    style Deliver fill:#e6fffb,stroke:#13c2c2
```

### 四层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│  Surface Layer                                                       │
│  飞书 Bot (lark-oapi WS) │ Dashboard (FastAPI+SSE) │ MCP Server     │
├─────────────────────────────────────────────────────────────────────┤
│  Agent Layer                                                         │
│  Intent → Planner → Research → Writer ⇄ Review → Builder            │
│  (共享 AgentState TypedDict，Pipeline 编排)                            │
├─────────────────────────────────────────────────────────────────────┤
│  Capability Layer                                                    │
│  doc_tool · slide_tool · canvas_tool · web_search · lark_tools       │
├─────────────────────────────────────────────────────────────────────┤
│  Infrastructure                                                      │
│  MiniMax M2.7 Client · Circuit Breaker · EventLog · Session FSM      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 技术亮点

### 1. Multi-Agent Pipeline：6 Agent 专业分工 + 共享 AgentState

参考 LangGraph TypedDict + CrewAI 角色分工模式，6 个 Agent 各司其职，通过共享 `AgentState`（TypedDict）通信，编排层 `pipeline.py` 串联：

| Agent | 职责 | 输入 | 输出 |
|-------|------|------|------|
| **IntentAgent** | 意图识别 · 任务分类（doc / ppt / trio / chat） | 用户消息 | `task_type` · `verdict` |
| **PlannerAgent** | LLM few-shot 生成结构化大纲 | intent | `outline[]` |
| **ResearchAgent** | MiniMax tool calling 联网搜索 | outline | `research_results[]` |
| **WriterAgent** | 按章节撰写、融合搜索数据 | outline + research | `draft_sections[]` |
| **ReviewAgent** | 5 维度自评（数据/结构/引用/密度/字数） | draft | `review_pass` · `review_feedback` |
| **BuilderAgent** | 组装飞书文档 / python-pptx 生成 PPT | draft + artifacts | `artifacts[]` |

### 2. MiniMax M2.7 Tool Calling 联网搜索

ResearchAgent 利用 MiniMax M2.7 的 **function calling** 能力，模型自主决定搜什么：

1. LLM 分析大纲章节 → 自主发出 `web_search` tool_call
2. 执行搜索获取实时数据（时间约束：2024-2026 年）
3. 搜索结果 feed back 给 LLM → 整理输出结构化研究报告

模型自主决策搜索意图，搜索质量随 LLM 能力自动提升。

### 3. ReviewAgent 自评迭代（参考 DeepPresenter）

WriterAgent 与 ReviewAgent 形成 generate-then-review 闭环：

- **审核维度**：数据支撑 / 结构完整 / 引用来源 / 内容密度 / 字数达标
- **最多 3 轮**迭代（`MAX_REVIEW_ITERATIONS = 3`），防止无限循环
- 每轮 feedback 精确注入，Writer 针对性修改

### 4. Human-in-the-Loop 大纲确认（参考 GenSlide AAAI 2025）

PlannerAgent 生成大纲后，通过飞书 CardKit 卡片发送给用户：

- **确认** → 进入 Research → Writer → Review → Builder
- **修改** → 用户反馈注入 state，Planner 重新生成
- 关键决策节点由人把关，平衡自动化效率与人类控制力

### 5. Claude Code 架构的错误恢复

参考 Anthropic Claude Code 工程实践：

- **步骤预算**（MAX_STEP_BUDGET=30）→ 防止 Agent 死循环
- **Circuit Breaker**（5 失败 → 熔断 5 分钟）→ 防级联故障
- **指数退避重试** → 应对瞬时 API 错误
- **上下文压缩** → Context overflow 时自动截断摘要

### 6. EventLog + SSE Dashboard 实时展示

每个 Agent 执行时 emit 事件到 `EventLog`，Dashboard 通过 SSE 推送：

- `agent.start` / `agent.done` / `agent.revise` 事件流
- Dify 风格三段式布局（Result / Detail / Tracing）
- 北京时间显示 + 30s heartbeat

### 7. 反向 MCP Server

`:8003` 暴露工具给 Cursor / Claude Desktop，评委可直接在 IDE 中调用：

```json
{"mcpServers": {"agent-pilot": {"url": "http://8.136.98.175/sse"}}}
```

### 8. 10 状态机 + LEGAL_TRANSITIONS

`session.py` 定义 10 个任务状态 + 合法转移矩阵，`stage_owners` 锁防止多人冲突：

```
IDLE → INTENT → PLANNING → RESEARCHING → WRITING → REVIEWING → BUILDING → DELIVERED → ARCHIVED
                                                                                      ↗
                                                                              FAILED ─┘
```

---

## 快速开始

### 方式一：本地开发

```bash
# 克隆仓库
git clone https://github.com/bcefghj/Agent-Pilot.git && cd Agent-Pilot

# 创建虚拟环境
python3 -m venv .venv && source .venv/bin/activate

# 安装依赖
pip install -e ".[bot,dashboard]"

# 配置环境变量
cp .env.example .env
# 编辑 .env，填写：
#   FEISHU_APP_ID=cli_xxx
#   FEISHU_APP_SECRET=xxx
#   MINIMAX_API_KEY=sk-xxx

# 运行单元测试（mock 模式，不消耗 API）
LLM_MOCK=1 pytest tests/ -q

# 运行真实 API 测试（需要 MINIMAX_API_KEY）
LLM_MOCK=0 python scripts/test_all_scenarios.py

# 启动全部服务
python -m pilot all
# 飞书 Bot:    WebSocket 长连接
# Dashboard:   http://localhost:8001
# MCP Server:  http://localhost:8003/sse
```

### 方式二：Docker 部署

```bash
docker-compose up -d
# 或单独构建
docker build -t agent-pilot .
docker run -d --env-file .env -p 8001:8001 -p 8003:8003 agent-pilot
```

### 方式三：服务器一键部署（Ubuntu 22.04）

```bash
ssh root@your-server
curl -fsSL https://raw.githubusercontent.com/bcefghj/Agent-Pilot/main/scripts/server/install.sh | bash
nano /opt/agent-pilot/.env   # 填写飞书 + MiniMax 凭据
systemctl start agent-pilot-bot agent-pilot-dashboard agent-pilot-mcp
```

### Cursor / Claude Desktop 接入反向 MCP

编辑 `~/.cursor/mcp.json`：

```json
{"mcpServers": {"agent-pilot": {"url": "http://your-server-ip/sse"}}}
```

---

## 飞书使用示例

| 场景 | 在飞书中说 | Agent-Pilot 做什么 | 预计耗时 |
|------|-----------|-------------------|----------|
| 方案文档 | `帮我写一份 AI Agent 多端协同方案` | Intent→Planner→Research→Writer→Review→Builder→飞书文档 | ~90s |
| PPT 制作 | `做 8 页关于飞书开放平台集成的 PPT` | ppt_pipeline：大纲→搜索→撰写→审核→python-pptx | ~120s |
| 三件套 | `AI Agent 办公自动化三件套` | trio_pipeline：文档 + PPT + 归档 | ~180s |
| 联网报告 | `搜索 2026 年 AI Agent 最新进展写份报告` | ResearchAgent 自主搜索→数据融合→生成报告 | ~90s |
| 模糊意图 | `帮我做个汇报` | IntentAgent → 主动澄清卡片 → 用户补充后进入 pipeline | — |
| 闲聊 | `你好` / `谢谢` | IntentAgent → chat_reply_card 友好回复 | <1s |

---

## 项目结构

```
Agent-Pilot/                         # 185 个源文件
├── pilot/                           # 核心 Python 包
│   ├── agents/                      # ⭐ Multi-Agent Pipeline 核心（8 文件）
│   │   ├── base.py                  #   BaseAgent 抽象类 + AgentState TypedDict
│   │   ├── intent.py                #   IntentAgent — 意图识别 · 任务分类
│   │   ├── planner.py               #   PlannerAgent — LLM few-shot 大纲规划
│   │   ├── researcher.py            #   ResearchAgent — MiniMax tool calling 联网搜索
│   │   ├── writer.py                #   WriterAgent — 按章节撰写 · 数据融合
│   │   ├── reviewer.py              #   ReviewAgent — 5 维度自评 · 迭代循环
│   │   ├── builder.py               #   BuilderAgent — 飞书 Doc / PPTX 组装交付
│   │   └── pipeline.py              #   doc / ppt / trio pipeline 编排
│   ├── runtime/                     # 状态机 + 编排器（6 文件）
│   │   ├── session.py               #   10 状态 FSM + LEGAL_TRANSITIONS
│   │   ├── orchestrator.py          #   任务编排器
│   │   ├── intent_router.py         #   意图路由
│   │   ├── planner.py               #   规划器
│   │   ├── harness.py               #   Harness 执行引擎
│   │   └── checkpoint.py            #   检查点持久化
│   ├── context/                     # 事件 + 记忆（5 文件）
│   │   ├── event_log.py             #   EventLog（Dashboard SSE 源）
│   │   ├── context_pack.py          #   上下文打包
│   │   ├── filesystem_memory.py     #   文件系统记忆
│   │   ├── agents_md.py             #   AGENTS.md 上下文
│   │   └── prompt_assembler.py      #   Prompt 组装器
│   ├── capability/                  # 工具 + 技能（15 文件）
│   │   ├── tools/                   #   doc · slide · canvas · web_media · lark_tools
│   │   ├── skills/                  #   4 个 SKILL.md 定义
│   │   └── workforce/               #   评估器 · 生成器 · Harness
│   ├── governance/                  # 安全治理（5 文件）
│   │   ├── owner_lock.py            #   stage_owners 锁
│   │   ├── policy.py                #   权限策略
│   │   ├── sandbox.py               #   沙箱隔离
│   │   ├── audit.py                 #   审计日志
│   │   └── otel.py                  #   OpenTelemetry
│   ├── surface/                     # UI 层（12 文件）
│   │   ├── feishu/                  #   lark-oapi WS bot · CardKit 卡片
│   │   ├── dashboard/               #   FastAPI SSE Dashboard
│   │   └── lark_mcp_runner.py       #   反向 MCP Server
│   └── llm/                         # LLM 客户端（3 文件）
│       ├── client.py                #   MiniMax M2.7 + Circuit Breaker
│       ├── web_search.py            #   联网搜索封装
│       └── safe_json.py             #   安全 JSON 解析
├── flutter_client/                  # Flutter 移动端（8 文件）
├── website/                         # 产品宣传网页 + Demo
├── scripts/                         # 部署 + 测试（7 文件）
│   ├── server/install.sh            #   一键部署脚本
│   ├── systemd/                     #   3 个 systemd unit
│   ├── nginx/                       #   nginx 反代配置
│   └── test_all_scenarios.py        #   PRD 全场景测试
├── tests/                           # 测试（16 文件）
│   ├── unit/                        #   单元测试
│   └── competition/                 #   竞赛 e2e
├── docs/                            # 文档（9 文件）
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── requirements.txt
└── .env.example
```

---

## API 文档

| Endpoint | 方法 | 说明 |
|----------|------|------|
| `/health` | GET | 健康检查，返回版本和运行时间 |
| `/dashboard` | GET | Dashboard HTML 页面 |
| `/api/sessions` | GET | 列出最近任务 sessions |
| `/api/sessions/{id}` | GET | 获取 session 详情 |
| `/api/events/{id}` | GET(SSE) | 实时事件流（Dashboard 订阅） |
| `/api/tools` | GET | 列出所有注册工具 |
| `/api/chat` | POST | Web Demo Chat（SSE 响应） |
| `/api/sync/stats` | GET | 多端同步统计 |
| `/ws` | WebSocket | 心跳 + 状态广播 |
| `/sync/ws/{room}` | WebSocket | 多端实时同步（Yjs） |
| `/artifacts/...` | GET | 静态产物下载 |
| `/sse` | GET(SSE) | MCP Server 工具暴露 |

---

## 评分维度对照

| 比赛维度 | 权重 | Agent-Pilot 对应实现 |
|----------|------|---------------------|
| **完整性与价值** | 50% | 解决"IM到演示稿"全链路痛点 · AI 主驾驶 90% 工作 · 14/14 场景通过 · 7×24 稳定运行 · 96%+ 时间节省 |
| **创新性** | 25% | 6 Agent Pipeline · MiniMax tool calling · ReviewAgent 自评 · Human-in-the-Loop · Circuit Breaker |
| **技术实现** | 25% | 四层架构 · 185 文件 · 16 单元测试 · CI/CD · systemd + nginx · 10 状态机 |

---

## Roadmap

| 阶段 | 内容 | 状态 |
|------|------|------|
| V1.0 | 基础飞书 Bot + 单 Agent | ✅ 已完成 |
| V1.5 | 错误恢复 + Circuit Breaker | ✅ 已完成 |
| V2.0 | Multi-Agent Pipeline + Dashboard + MCP | ✅ 当前版本 |
| V2.1 | 语音输入支持 + 多语言 | 🔄 规划中 |
| V3.0 | 知识库集成 + RAG + 团队协作 | 📋 设计中 |

---

## 相关论文 & 设计参考

| 参考 | 年份 | 我们借鉴了什么 |
|------|------|---------------|
| **GenSlide** (AAAI 2025) | 2025 | Human-in-the-Loop：Approve / Revise 大纲确认 |
| **DeepPresenter** | 2024 | Generate-then-Review：自评迭代提升质量 |
| **CrewAI** | 2024 | Agent 角色分工 + Pipeline 编排模式 |
| **LangGraph** | 2024 | TypedDict 共享状态 + 流式编排 |
| **Claude Code** (Anthropic) | 2026 | 错误恢复决策树 + 步骤预算 + 上下文压缩 |
| **Harness Engineering** | 2026 | 五层架构分离 |

---

## 团队

| 成员 | 角色 | 联系方式 |
|------|------|----------|
| [李洁盈](https://janeliii.netlify.app/) | 产品设计 / UI·UX / 内容运营 | JieyingLiii@outlook.com |
| [戴尚好](https://bcefghj.github.io) | 全栈开发 / Multi-Agent 架构 / 部署 | bcefghj@163.com |

---

## License

[MIT](LICENSE) · Copyright © 2026 戴尚好 & 李洁盈

---

<p align="center">
  <strong>Agent-Pilot</strong> · 从 IM 对话到演示稿的一键智能闭环<br/>
  2026 飞书 AI 校园挑战赛
</p>
