# Agent-Pilot V2.0 — Multi-Agent Pipeline 驱动的 IM 协同办公助手

> 在飞书 IM 中通过自然语言触发，6 个专业 AI Agent（Intent / Planner / Research / Writer / Review / Builder）协作完成从需求理解到文档 / PPT / 画布交付的全链路自动化。

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-V2.0-orange.svg)]()

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

**核心路径**：`User → IntentAgent → PlannerAgent → ResearchAgent → WriterAgent ⇄ ReviewAgent → BuilderAgent → 飞书 Doc / PPT`

---

## 技术亮点

### 1. Multi-Agent Pipeline：6 Agent 专业分工 + 共享 AgentState

参考 LangGraph TypedDict + CrewAI 角色分工模式，6 个 Agent 各司其职，通过共享 `AgentState`（TypedDict）通信，编排层 `pipeline.py` 串联：

| Agent | 职责 | 输入 | 输出 |
|-------|------|------|------|
| **IntentAgent** | 意图识别 · 任务分类（doc / ppt / trio / chat） | 用户消息 | `task_type` · `_verdict` |
| **PlannerAgent** | LLM few-shot 生成结构化大纲 | intent | `outline[]` |
| **ResearchAgent** | MiniMax tool calling 联网搜索 | outline | `research_results[]` |
| **WriterAgent** | 按章节撰写、融合搜索数据 | outline + research | `draft_sections[]` |
| **ReviewAgent** | 5 维度自评（数据/结构/引用/密度/字数） | draft | `review_pass` · `review_feedback` |
| **BuilderAgent** | 组装飞书文档 / python-pptx 生成 PPT | draft + artifacts | `artifacts[]` |

```
pilot/agents/
├── base.py         # BaseAgent 抽象类 + AgentState TypedDict
├── intent.py       # IntentAgent — 意图识别
├── planner.py      # PlannerAgent — 大纲规划
├── researcher.py   # ResearchAgent — 联网搜索
├── writer.py       # WriterAgent — 内容撰写
├── reviewer.py     # ReviewAgent — 质量审核
├── builder.py      # BuilderAgent — 产物组装交付
└── pipeline.py     # doc_pipeline / ppt_pipeline / trio_pipeline 编排
```

### 2. MiniMax M2.7 Tool Calling 联网搜索

ResearchAgent 不硬编码搜索关键词，而是利用 MiniMax M2.7 的 **function calling** 能力让模型自主决定搜什么：

1. LLM 分析大纲章节 → 自主发出 `web_search` tool_call
2. 我们执行搜索（DDG + Bing 双引擎兜底）
3. 搜索结果 feed back 给 LLM → 整理输出结构化研究报告

模型自主决策搜索意图，而非规则触发，搜索质量随 LLM 能力提升。

### 3. ReviewAgent 自评迭代

参考 **DeepPresenter** 论文的 *generate-then-review* 范式，WriterAgent 与 ReviewAgent 形成闭环：

```
Writer 撰写 → Reviewer 5 维度打分 → 不通过？→ feedback 注入 → Writer 重写
                                      ↓ 通过
                                   Builder 交付
```

- 审核维度：数据支撑 / 结构完整 / 引用来源 / 内容密度 / 字数达标
- 最多迭代 **3 轮**（`MAX_REVIEW_ITERATIONS = 3`），防止无限循环
- 每轮 feedback 注入 `state["intent"]`，Writer 针对性修改

### 4. Human-in-the-Loop 大纲确认

参考 **GenSlide** 的 Approve / Revise 设计，PlannerAgent 生成大纲后，通过飞书 CardKit 卡片发送给用户确认：

- **确认** → 进入 Research → Writer → Review → Builder
- **修改** → 用户反馈注入 state，Planner 重新生成
- 关键决策节点由人把关，避免 Agent 跑偏

### 5. EventLog + SSE Dashboard 实时展示

每个 Agent 执行时 emit 事件到 `EventLog`，Dashboard 通过 SSE 实时推送：

- `agent.start` / `agent.done` / `agent.revise` 事件流
- 中文化事件描述 + 进度条 + 30s heartbeat
- 用户在飞书等待时，可打开 Dashboard 看到 Agent 协作的实时过程

### 6. 反向 MCP Server

`:8003` 暴露工具给 Cursor / Claude Desktop，评委可直接在 IDE 中调用：

```json
{"mcpServers": {"agent-pilot": {"url": "http://8.136.98.175/sse"}}}
```

### 7. 10 状态机 + LEGAL_TRANSITIONS

`session.py` 定义 10 个任务状态 + 合法转移矩阵，`stage_owners` 锁防止多人冲突：

```
IDLE → INTENT → PLANNING → RESEARCHING → WRITING → REVIEWING → BUILDING → DELIVERED → ARCHIVED
                                                                                      ↗
                                                                              FAILED ─┘
```

---

## 快速开始

### 本地开发

```bash
git clone https://github.com/bcefghj/Agent-Pilot.git && cd Agent-Pilot
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[bot,dashboard]"
cp .env.example .env  # 填写以下凭据

# .env 需要：
# FEISHU_APP_ID=cli_xxx
# FEISHU_APP_SECRET=xxx
# MINIMAX_API_KEY=xxx

# 跑测试
LLM_MOCK=1 pytest tests/ -q

# 启动全部服务
python -m pilot all
# 飞书 Bot:    WS 长连接
# Dashboard:   http://localhost:8001
# MCP Server:  http://localhost:8003/sse
```

### 服务器部署（Ubuntu 22.04）

```bash
ssh root@your-server
curl -fsSL https://raw.githubusercontent.com/bcefghj/Agent-Pilot/main/scripts/server/install.sh | bash
nano /opt/agent-pilot/.env   # 填飞书 + MiniMax 凭据
systemctl start agent-pilot-bot
```

详见 [`docs/DEPLOY.md`](docs/DEPLOY.md)。

### Cursor / Claude Desktop 接入反向 MCP

编辑 `~/.cursor/mcp.json`：

```json
{"mcpServers": {"agent-pilot": {"url": "http://your-server-ip/sse"}}}
```

详见 [`docs/MCP_USAGE.md`](docs/MCP_USAGE.md)。

---

## 飞书使用示例

以 AI 校园赛相关场景为例：

| 场景 | 在飞书中说 | Agent-Pilot 做什么 |
|------|-----------|-------------------|
| 方案文档 | `帮我写一份 AI Agent 多端协同方案` | Intent→Planner→Research 联网搜索→Writer 撰写→Review 自评→Builder 写入飞书文档 |
| PPT 制作 | `做 8 页关于飞书开放平台集成的 PPT` | ppt_pipeline：大纲→搜索→撰写→审核→python-pptx 生成 .pptx |
| 三件套 | `AI Agent 办公自动化三件套` | trio_pipeline：文档 + PPT + 归档，一次请求三份产物 |
| 联网报告 | `搜索 2026 年 AI Agent 最新进展写份报告` | ResearchAgent MiniMax tool calling 自主搜索→数据融合→生成报告 |
| 模糊意图 | `帮我做个汇报` | IntentAgent 识别 → 主动澄清卡片 → 用户补充后进入 pipeline |
| 闲聊 | `你好` / `谢谢` | IntentAgent 判定 chat → 友好回复，不沉默 |

---

## 项目结构

```
Agent-Pilot/
├── pilot/
│   ├── agents/              # ⭐ Multi-Agent Pipeline 核心
│   │   ├── base.py          # BaseAgent 抽象类 + AgentState TypedDict
│   │   ├── intent.py        # IntentAgent — 意图识别 · 任务分类
│   │   ├── planner.py       # PlannerAgent — LLM few-shot 大纲规划
│   │   ├── researcher.py    # ResearchAgent — MiniMax tool calling 联网搜索
│   │   ├── writer.py        # WriterAgent — 按章节撰写 · 数据融合
│   │   ├── reviewer.py      # ReviewAgent — 5 维度自评 · 迭代循环
│   │   ├── builder.py       # BuilderAgent — 飞书 Doc / PPTX 组装交付
│   │   └── pipeline.py      # doc / ppt / trio pipeline 编排
│   ├── runtime/             # IntentRouter · Planner · Orchestrator · Session 状态机
│   ├── context/             # EventLog · ContextPack · Filesystem Memory
│   ├── capability/tools/    # doc · slide · canvas · web_media · lark_tools
│   ├── governance/          # 权限 · 审计 · owner_lock
│   ├── surface/
│   │   ├── feishu/          # lark-oapi WS bot · CardKit 卡片
│   │   ├── dashboard/       # FastAPI SSE Dashboard（实时 Agent 协作过程）
│   │   └── lark_mcp_runner.py  # 反向 MCP Server
│   └── llm/                 # MiniMax client · web_search · safe_json
├── scripts/
│   ├── server/              # install.sh 一键部署
│   ├── systemd/             # systemd unit 文件
│   └── nginx/               # 反代配置
├── tests/
│   ├── unit/                # 单元测试
│   └── competition/         # 竞赛 e2e 测试
├── docs/
│   ├── DEPLOY.md            # 服务器部署文档
│   ├── MCP_USAGE.md         # Cursor/Claude Desktop 接入
│   └── ARCHITECTURE.md      # 架构设计详解
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── requirements.txt
├── .env.example
└── README.md
```

---

## 评分维度对照

| 比赛评分维度 | 权重 | Agent-Pilot 对应实现 |
|-------------|------|---------------------|
| **创新性** | 25% | Multi-Agent Pipeline（6 Agent 专业分工 + 共享 AgentState）· MiniMax tool calling 联网搜索（模型自主决定搜什么）· ReviewAgent 自评迭代（参考 DeepPresenter）· Human-in-the-Loop 大纲确认（参考 GenSlide）|
| **完成度** | 25% | 从意图识别到飞书文档/PPT/画布交付的全链路闭环 · doc / ppt / trio 三种 pipeline · EventLog + SSE Dashboard 实时展示 · 反向 MCP Server · 10 状态机防冲突 |
| **实用性** | 25% | 飞书 IM 原生体验（无需跳出聊天）· 联网搜索获取真实数据 · 自评迭代保障内容质量 · 文档/PPT/三件套一句话交付 · CardKit 卡片交互 |
| **展示效果** | 25% | Mermaid 架构图 · SSE Dashboard 实时观察 Agent 协作 · 飞书内产物直接预览 · Cursor MCP 工具演示 · 清晰的代码结构和文档 |

---

## 相关论文 & 设计参考

| 参考 | 借鉴点 |
|------|--------|
| **GenSlide** (AAAI 2025) | Human-in-the-Loop：Approve / Revise 大纲确认机制 |
| **DeepPresenter** | Generate-then-Review：自评迭代提升内容质量 |
| **CrewAI** | Agent 角色分工 + Pipeline 编排模式 |
| **LangGraph** | TypedDict 共享状态 + 流式编排 |

---

## 团队

| 成员 | 角色 |
|------|------|
| [戴尚好](https://bcefghj.github.io) | 全栈开发 / Multi-Agent 架构 / 部署 |
| [李洁盈](https://janeliii.netlify.app/) | 产品设计 / UI·UX / 内容运营 |

---

## License

[MIT](LICENSE) · Copyright © 2026 戴尚好 & 李洁盈
