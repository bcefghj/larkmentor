# LarkMentor

> **飞书 IM 上的双引擎 AI 协同助手** —— 挡掉不该打断你的，接住打断你的人想说的。

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue)]()
[![Tests](https://img.shields.io/badge/pytest-178%20passed-brightgreen)]()
[![Code](https://img.shields.io/badge/Python-14%2C511%20lines-orange)]()
[![License](https://img.shields.io/badge/License-MIT-yellow)]()
[![飞书 AI 校园挑战赛](https://img.shields.io/badge/2026-飞书AI校园挑战赛-purple)]()

**在线体验**: http://118.178.242.26/ &nbsp;|&nbsp; **技术报告**: [`larkmentor_report.pdf`](larkmentor_report.pdf)

---

## 解决什么问题

知识工作者每天在飞书上被两件事消耗：**不该看的消息** 和 **不会说的话**。

| 痛点 | 数据 | LarkMentor 的解法 |
|------|------|-------------------|
| 每被打断一次，平均 **23 分 15 秒** 回到原任务 | Mark et al., CHI 2008 | **Smart Shield** · 6 维分类，挡掉 80% 低优先级消息 |
| **80%+** 组织知识是隐性的 | Nonaka 1995 | **Mentor 4 Skills** · 替新人起草消息/任务/周报/入职 |

没有产品把这两件事一起解过。LarkMentor 是第一个。

---

## 架构

```
接口层     Feishu Bot (WebSocket)  ·  MCP Server (HTTP)  ·  Dashboard (FastAPI)
              ↓
业务层     Smart Shield (6维分类+分级推送)  ·  Mentor 4 Skills (Write/Task/Review/Onboard)
           Recovery Card (双线交点: 上半"挡了什么" + 下半"起草了什么")
              ↓
记忆层     Working → Compaction → Archival  ·  FlowMemory.md 6级层次  ·  KB RAG
              ↓
安全栈     Permission → Inject → Hook → PII → Denylist → RateLimit → Sandbox → Audit (8层)
```

借鉴 Anthropic Claude Code 7 大支柱（ToolRegistry / HookSystem / SkillLoader / Permission / 6-tier Memory / MCP / AuditLog），详见 [`larkmentor_report.pdf`](larkmentor_report.pdf) Part III。

---

## 快速开始

### 1. 安装依赖

```bash
git clone https://github.com/bcefghj/larkmentor.git
cd larkmentor
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置飞书开发者平台

> 详细步骤见 **[FEISHU_SETUP.md](FEISHU_SETUP.md)**（含截图说明、权限清单、常见报错）

简要步骤：
1. 在[飞书开放平台](https://open.feishu.cn/app) 创建**自建应用**
2. 开启**机器人**能力
3. 申请以下 **API 权限**：`im:message`、`im:message:send_as_bot`、`im:chat:readonly`、`contact:user.base:readonly`、`docx:document`、`bitable:app`
4. 订阅**事件**：`im.message.receive_v1` 和 `card.action.trigger`（选「长连接」模式）
5. **发布版本**（每次改权限后都要发布一次）

然后配置 `.env`：

```bash
cp .env.example .env
```

| 变量 | 说明 | 获取方式 |
|------|------|----------|
| `FEISHU_APP_ID` | 飞书应用 ID | 飞书开放平台 → 凭证与基础信息 |
| `FEISHU_APP_SECRET` | 飞书应用密钥 | 同上 |
| `ARK_API_KEY` | 火山方舟 API Key | [火山方舟控制台](https://console.volcengine.com/ark) |
| `ARK_BASE_URL` | 方舟 API 地址 | `https://ark.cn-beijing.volces.com/api/coding/v3` |
| `ARK_MODEL` | 模型名 | `doubao-seed-2.0-pro` |

### 3. 运行测试

```bash
PYTHONPATH=. pytest tests/ -q --ignore=tests/e2e --ignore=tests/simulator
# 预期: 178+ passed
```

### 4. 启动

```bash
python main.py
```

Bot 启动后在飞书中搜索机器人名称即可开始使用。

### 5. 启动 Dashboard 和 MCP Server（可选）

```bash
# Dashboard（端口 8001）
uvicorn dashboard.server:app --host 0.0.0.0 --port 8001

# MCP Server（端口 8767）
python -m core.mcp_server.server --transport http --port 8767
```

---

## 使用方式

| 指令 | 功能 |
|------|------|
| `开启专注 30 分钟` | 进入专注模式，低优先级消息被拦截 |
| `结束专注` | 退出专注，弹出 Recovery Card |
| `帮我看：<消息>` | MentorWrite — 起草 3 版不同语气的回复 |
| `任务确认：<任务描述>` | MentorTask — 模糊度评估 + 澄清问题 |
| `写周报` | MentorReview — STAR 结构周报 |
| `开启新人模式` | MentorOnboard — 5 问入职 |
| `导入知识：<文本>` | 向个人知识库导入文档 |
| `我的状态` | 查看当前状态 |
| `删除我的数据` | 物理删除所有个人数据 |

---

## 代码结构

```
larkmentor/
├── main.py                  # 主入口：飞书长连接 + 定时任务
├── config.py                # 环境变量配置
├── requirements.txt         # 依赖（lark-oapi, openai, fastapi, rank-bm25, ...）
├── .env.example             # 环境变量模板
├── larkmentor_report.pdf    # 完整技术报告
│
├── bot/                     # 飞书 Bot 接口
│   ├── event_handler.py     #   消息事件 + 卡片回调
│   ├── feishu_client.py     #   飞书 API 客户端
│   ├── message_sender.py    #   消息发送
│   └── card_builder.py      #   卡片构建
│
├── core/                    # 核心逻辑
│   ├── smart_shield.py      #   Smart Shield 主链路
│   ├── smart_shield_v3.py   #   v3 增强链路（8层安全栈全经过）
│   ├── classification_engine.py  # 6 维分类引擎
│   ├── recovery_card.py     #   Recovery Card（双线交点）
│   ├── sender_profile.py    #   发件人画像
│   ├── analytics.py         #   日报/统计
│   │
│   ├── mentor/              #   Mentor 4 Skills
│   │   ├── mentor_write.py  #     MentorWrite: NVC 消息起草
│   │   ├── mentor_task.py   #     MentorTask: 任务澄清
│   │   ├── mentor_review.py #     MentorReview: STAR 周报
│   │   ├── mentor_onboard.py#     MentorOnboard: 5 问入职
│   │   ├── knowledge_base.py#     用户级 RAG (Doubao Embedding + BM25)
│   │   ├── mentor_router.py #     Skill 路由
│   │   ├── proactive_hook.py#     主动出手频控
│   │   ├── growth_doc.py    #     成长档案
│   │   └── skills_init.py   #     Skill 注册
│   │
│   ├── runtime/             #   Claude Code 风格运行时
│   │   ├── tool_registry.py #     ToolRegistry
│   │   ├── hook_runtime.py  #     HookSystem facade
│   │   ├── skill_loader.py  #     SkillLoader
│   │   └── permission_facade.py  # PermissionManager facade
│   │
│   ├── security/            #   8 层安全栈
│   │   ├── permission_manager.py  # 5 级权限
│   │   ├── transcript_classifier.py # Prompt Injection 检测
│   │   ├── hook_system.py   #     生命周期拦截
│   │   ├── pii_scrubber.py  #     PII 脱敏
│   │   ├── keyword_denylist.py   # 高危词拦截
│   │   ├── rate_limiter.py  #     速率限制
│   │   ├── tool_sandbox.py  #     API 白名单
│   │   └── audit_log.py     #     审计日志
│   │
│   ├── flow_memory/         #   FlowMemory 记忆引擎
│   │   ├── working.py       #     Working Memory
│   │   ├── compaction.py    #     压缩层
│   │   ├── archival.py      #     归档层
│   │   └── flow_memory_md.py#     6 级层次 resolver
│   │
│   ├── feishu_advanced/     #   飞书 7 个 API
│   │   ├── calendar_busy.py #     日历
│   │   ├── wiki_search.py   #     Wiki
│   │   ├── minutes_fetch.py #     妙记
│   │   ├── reaction_api.py  #     Reaction
│   │   ├── reply_thread.py  #     话题回复
│   │   ├── task_v2.py       #     任务
│   │   └── urgent_api.py    #     加急
│   │
│   ├── mcp_server/          #   MCP 协议 (18 个工具)
│   │   ├── server.py        #     HTTP + stdio Server
│   │   └── tools.py         #     工具注册
│   │
│   └── work_review/         #   工作回顾
│       ├── weekly_report.py #     周报
│       └── monthly_wrapped.py    # 月报
│
├── llm/                     # LLM 调用
│   ├── llm_client.py        #   OpenAI 兼容客户端 (火山方舟)
│   └── prompts.py           #   Prompt 模板
│
├── memory/                  # 持久化
│   ├── user_state.py        #   用户状态管理
│   ├── context_snapshot.py  #   上下文快照
│   └── interruption_log.py  #   打断日志
│
├── dashboard/               # Web 面板
│   ├── server.py            #   FastAPI Dashboard
│   ├── mentor_stats.py      #   Mentor 统计 API
│   └── static/              #   前端页面
│
├── utils/                   # 工具函数
│   ├── feishu_api.py        #   飞书 API 封装
│   └── time_utils.py        #   时间工具
│
├── tests/                   # 测试 (178+ 用例)
│   ├── test_smart_shield.py
│   ├── test_mentor.py
│   ├── test_recovery_card.py
│   ├── test_runtime.py
│   ├── test_security_stack.py
│   ├── test_flow_memory.py
│   ├── test_knowledge_base.py
│   ├── ...
│   └── simulator/           #   12 个 YAML 场景
│       └── scenarios/
│
└── deploy/                  # 部署 (阿里云一键)
    ├── deploy_lark_mentor.sh
    ├── rollback.sh
    └── smoke_test.sh
```

---

## 部署（阿里云 2C2G）

```bash
cd deploy
bash deploy_lark_mentor.sh
```

脚本自动：本地 pytest 验证 → 打包上传 → 服务器解压装依赖 → 写 systemd → 冷切换 → smoke test 15 项验证。失败自动 `rollback.sh`。

部署后 3 个服务运行：

| 服务 | 端口 | 说明 |
|------|------|------|
| `larkmentor.service` | — | 飞书 Bot（WebSocket 长连接） |
| `larkmentor-dashboard.service` | 8001 | Dashboard |
| `larkmentor-mcp.service` | 8767 | MCP HTTP Server |

---

## 量化指标

| 指标 | 数值 |
|------|------|
| Python 文件 | 96 个 |
| 代码行数 | 14,511 行 |
| pytest 用例 | 178 个，全过 |
| Promptfoo 红队 | 14/14 通过 |
| 6 维分类准确率 | 99%（102 YAML 测试集） |
| LLM 调用率 | < 12%（规则短路） |
| P99 延迟 | 规则路径 < 80ms / LLM < 2.2s |
| MCP 工具 | 18 个 |
| 飞书 API | 7 个（IM/Docx/Bitable/Calendar/Wiki/Minutes/Reaction） |
| 安全栈 | 8 层全链路 |
| 部署 | 阿里云 2C2G，systemd × 3 |

---

## 技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| 飞书 SDK | `lark-oapi` | WebSocket 长连接 |
| LLM | 火山方舟 Doubao | Coding Plan 免费额度 |
| Embedding | Doubao Embedding | 与 LLM 同一个 API Key |
| 检索兜底 | `rank-bm25` | Embedding 挂了自动降级 |
| Web | `fastapi` + `uvicorn` | Dashboard + MCP |
| 调度 | `apscheduler` | 日报/周报/日历轮询 |
| 存储 | SQLite + JSON | 轻量，2C2G 友好 |

不引入 LangGraph / CrewAI / LangChain——遵循 Claude Code「纯 prompt + Python facade」哲学，2C2G 可部署、可审计、可解释。

---

## 赛道对应

| 志愿 | 赛道 | 对应 |
|------|------|------|
| 1 | 飞书 AI 产品创新 · 课题二 | LarkMentor 全栈 |
| 2 | OpenClaw · 课题二（长程 Memory） | `core/flow_memory/` |
| 3 | AI 安全 · 课题一（客户端防护） | `core/security/` |

同一份代码，三种切片。

---

## 团队

| 成员 | 角色 |
|------|------|
| [戴尚好](https://bcefghj.github.io) | 全栈 / Agent 安全 / 部署（中国科学技术大学 硕士） |
| [李洁盈](https://janeliii.netlify.app/) | 产品 / UI / 内容 |

---

## License

MIT
