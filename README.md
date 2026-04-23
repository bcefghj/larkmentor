# LarkMentor v2 · Agent-Pilot

> **从 IM 对话到演示稿的一键智能闭环**
>
> AI Agent 主驾驶 · GUI 四端（iOS / Android / macOS / Windows）Co-pilot · Yjs CRDT 实时同步

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue)]()
[![Tests](https://img.shields.io/badge/pytest-218%20passed-brightgreen)]()
[![Flutter](https://img.shields.io/badge/Flutter-4端一套代码-02569B)]()
[![CRDT](https://img.shields.io/badge/Yjs-CRDT%20offline%20merge-violet)]()
[![Security](https://img.shields.io/badge/安全栈-8层全链路-red)]()
[![MCP](https://img.shields.io/badge/MCP-21个工具-blueviolet)]()
[![License](https://img.shields.io/badge/License-MIT-yellow)]()

**在线体验**：http://118.178.242.26/ &nbsp;|&nbsp;
**Pilot 驾驶舱**：http://118.178.242.26/dashboard/pilot &nbsp;|&nbsp;
**技术报告**：[larkmentor_report.pdf](larkmentor_report.pdf)

---

## 🚀 一分钟快速体验

在飞书中私聊 **LarkMentor** 机器人，发送：

```
/pilot 把最近讨论整理成产品方案 + 架构图 + 评审PPT
```

**40秒后自动生成**：📄 飞书文档 + 🎨 架构白板 + 📊 演示PPT

---

## v2 一句话（赛题对齐）

赛题「基于 IM 的办公协同智能助手 · Agent-Pilot」要求：**从一次 IM 对话开始，Agent 自动串联 IM + 文档 + 演示稿/画布，实现多端实时同步的全链路自动化**。

本项目实现：

| 赛题要求 | 本项目实现 |
| --- | --- |
| 多端协同框架（移动 + 桌面 实时同步） | Flutter iOS/Android/macOS/Windows 四端一套代码 + `y-py` WebSocket CRDT Hub |
| 场景 A 意图入口 | 飞书 IM 群/私聊 + `/pilot` 指令，Flutter 长按语音 |
| 场景 B 任务理解与规划 | `PilotPlanner`：Doubao LLM DAG + 纯 Python Heuristic 双栈 |
| 场景 C 文档/白板生成 | `doc_tool.py`（飞书 Docx API）+ `canvas_tool.py`（tldraw 场景 + 飞书画板双写） |
| 场景 D 演示稿生成与排练 | `slide_tool.py`（Slidev markdown → pptx + 演讲稿） |
| 场景 E 多端协作与一致性 | `core/sync/` CRDT Hub + Flutter `OfflineCache` + 离线合并对账 |
| 场景 F 总结与交付 | `archive_tool.py`：manifest + 飞书 Docx 摘要 + 分享页 |
| 加分：离线支持 | Yjs 原生 offline merge + Flutter SQLite 本地缓存 |
| 加分：高级 Agent 能力 | Proactive clarification / 讨论总结 / 下一步推荐 |
| 加分：富媒体画布 | canvas `shape_type`: node / arrow / image / table / sticky |
| 加分：第三方平台集成 | 飞书 7 API（IM/Docx/Bitable/Calendar/Wiki/Minutes/Reaction）+ 规划中的 Board / Drive / Slides |

---

## 目录

- [v2 Agent-Pilot 架构一览](#v2-agent-pilot-架构一览)
- [快速跑通（3 分钟）](#快速跑通3-分钟)
- [Flutter 四端客户端](#flutter-四端客户端)
- [Demo 脚本](#demo-脚本)
- [原 LarkMentor v1（消息守护 + 表达引导）](#原-larkmentor-v1消息守护--表达引导)
- [系统架构](#系统架构)
- [飞书开发者平台配置](#飞书开发者平台配置)
- [服务器部署（阿里云 v2）](#服务器部署阿里云-v2)
- [使用指令大全](#使用指令大全)
- [代码结构](#代码结构)
- [量化指标](#量化指标)
- [技术选型说明](#技术选型说明)
- [团队](#团队)

---

## v2 Agent-Pilot 架构一览

```
┌────────────────────────────────────────────────────────────────────┐
│  输入层                                                             │
│  飞书 IM (群/私聊, 文本/语音)  ·  Flutter iOS/Android/macOS/Windows │
│                    ·  Web Dashboard (评委入口)                      │
└──────────────────────────────┬─────────────────────────────────────┘
                               ↓
┌────────────────────────────────────────────────────────────────────┐
│  Agent-Pilot 后端                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │  Gateway     │  │  Planner     │  │  Advanced Agent          │ │
│  │ (FastAPI)    │→ │ (Doubao LLM  │→ │ 主动澄清 / 讨论总结 /     │ │
│  │              │  │  + Heuristic)│  │ 下一步推荐                │ │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘ │
│                               ↓                                     │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  DAG Orchestrator (ThreadPool, parallel groups, dependency)  │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                               ↓                                     │
│  ┌──────────┬───────────┬──────────┬──────────┬──────────────┐   │
│  │im.fetch  │doc.create │canvas.*  │slide.*   │archive.bundle│   │
│  │mentor.*  │doc.append │          │rehearse  │              │   │
│  └──────────┴───────────┴──────────┴──────────┴──────────────┘   │
└──────────────────────────────┬─────────────────────────────────────┘
                               ↓
┌────────────────────────────────────────────────────────────────────┐
│  多端同步层 (Yjs CRDT Hub)                                         │
│  core/sync/crdt_hub.py  ·  core/sync/ws_server.py                  │
│  y-py YDoc per plan · WebSocket fanout · 离线 log + reconcile      │
└──────────────────────────────┬─────────────────────────────────────┘
                               ↓ (broadcast event/state/yupdate)
    ┌──────────────────┬──────────────────┬──────────────────┐
    │  飞书 Bot        │  Flutter 4 端     │  Web Dashboard    │
    │  发汇总卡片       │  原生 Canvas/PPT  │  tldraw + Tiptap │
    └──────────────────┴──────────────────┴──────────────────┘
```

---

## 快速跑通（3 分钟）

```bash
git clone https://github.com/bcefghj/larkmentor.git
cd larkmentor
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # 填入飞书 App ID / Secret、ARK API Key

# 启动全部 3 个服务
bash run_services.sh

# 浏览器打开：
#   http://localhost:8001/dashboard/pilot   ← Agent-Pilot 驾驶舱
#   http://localhost:8001/                  ← 原有 Dashboard
```

跑通无网络也能玩：文档生成、画布、PPT 都会 fallback 到本地 markdown/JSON 文件，放在 `data/pilot_artifacts/`，可通过 `http://localhost:8001/artifacts/<file>` 访问。

### 最小飞书 Bot Demo

在飞书里私聊机器人：

```
/pilot 把本周关于 Agent-Pilot 的讨论整理成产品方案 + 评审 PPT，并画一张架构图
```

Bot 会立即回复计划 + 进度链接，后台 Orchestrator 并行跑完 8 步，结束后再发一条汇总。

---

## Flutter 四端客户端

一套代码跑 **iOS / Android / macOS / Windows**，作为 Agent-Pilot 的 **Co-pilot GUI 驾驶舱**。

```bash
cd mobile_desktop
flutter pub get
flutter run -d macos     # or: ios / android / windows
```

5 个原生页面 + 1 个设置页：

| 页面 | 场景 | 功能 |
| --- | --- | --- |
| Agent-Pilot | A/B/E | 启动 Pilot、查看 DAG 进度、实时事件流 |
| 文档协作 | C | 内嵌 Web 驾驶舱，保证四端一致 |
| 画布协作 | C | 原生 `CustomPaint` 渲染 tldraw 场景 JSON |
| 演示稿 | D | 读取 Slidev outline + 演讲稿，排练模式 |
| 语音指令 | A | 长按录音 → 后端 ASR → 触发 `/pilot` |
| 设置 | - | 修改后端 URL / open_id |

全部页面共享 `SyncService` WebSocket，后端 CRDT Hub 任意客户端操作都会实时推送。

---

## Demo 脚本

完整 5 分钟评审 demo 录屏脚本：[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)。

### 6 场景独立演示

| 场景 | 独立触发命令 |
| --- | --- |
| A 意图入口 | 飞书语音 / 文本 `/pilot ...` |
| B 任务规划 | `/pilot 处理一下` → 看 Planner 自动澄清 |
| C 文档生成 | `/pilot 起草 Q2 规划文档` |
| C 画布生成 | `/pilot 画一张 Agent-Pilot 架构图` |
| D PPT 生成 | `/pilot 为 AI 比赛写评审 PPT` |
| E 多端同步 | 移动端修改 → 桌面端实时刷新 |
| F 归档交付 | 任何 Plan 结束都会生成 `/pilot/<plan_id>` 分享页 |

---

## 原 LarkMentor v1（消息守护 + 表达引导）

---

LarkMentor 是一个运行在**飞书 IM** 里的 AI Bot，同时解决知识工作者每天面临的两个问题：

**问题一：被消息打断，回不了神**

> 知识工作者每被打断一次，平均需要 **23 分 15 秒** 才能回到原来的工作状态。
> （来源：UC Irvine Gloria Mark, CHI 2008）

飞书群里每天收几百条消息，其中大部分不需要立刻看——但你不点开不知道重不重要。

**问题二：新人不会说话，老员工知识不传**

> 企业里 **80%+** 的关键知识是隐性的——存在老员工脑子里，从未被写下来。新员工平均需要 **8-12 个月** 才能达到全产能。
> （来源：Nonaka 1995 / SHRM 2023）

新人在群里犹豫半分钟、删了 3 遍才发出「好的」——不知道该怎么问问题、怎么写周报、怎么确认任务。

**LarkMentor 的解法：两件事放在同一个 Bot 里**

| 服务线 | 做什么 | 核心模块 |
|--------|--------|----------|
| **Smart Shield（消息层守护）** | 6 维分类引擎挡掉 80% 低优先级消息；专注结束后用 Recovery Card 帮你快速回到上下文 | `core/classification_engine.py`、`core/recovery_card.py` |
| **Mentor（表达层引导）** | 替你起草消息回复、澄清模糊任务、生成 STAR 周报、完成新人入职 5 问——**永远是草稿，永远不自动发送** | `core/mentor/` |

两条服务线共享同一份组织知识库（用户级 RAG）和记忆系统（FlowMemory），这是它们真正"合体"而不是"拼凑"的原因。

---

## 三个赛道志愿

LarkMentor 同一份代码天然覆盖三条赛道，已按报名表填写三个志愿：

### 第一志愿 · 飞书 AI 产品创新 · 课题二
**基于 IM 的办公协同智能助手**

LarkMentor 全栈产品直接对齐课题二：
- 原生飞书 Bot（`lark-oapi` WebSocket 长连接），不是浏览器插件，不是 Mini App
- 串联飞书 **7 个 API**：IM / Docx / Bitable / Calendar / Wiki / 妙记 / Reaction
- 消息层（Smart Shield）+ 表达层（Mentor 4 Skills）双线覆盖 IM 高频场景
- Recovery Card：一张卡同时呈现"挡了什么"和"起草了什么"，是双线产品的工程交点
- 代码入口：整个仓库

### 第二志愿 · 飞书 OpenClaw · 课题二
**企业级长程协作 Memory 系统**

LarkMentor 内置的 `core/flow_memory/` 是一个独立的记忆引擎（FlowMemory），可作为 OpenClaw SDK 直接调用：
- **三层架构**：Working（当前会话滑窗）→ Compaction（LLM 摘要压缩）→ Archival（长期 SQLite 归档）
- **6 级层次注入**：Enterprise → Workspace → Department → Group → User → Session，低层覆盖高层，每次 LLM 调用前自动合并注入 system prompt
- **MCP 暴露**：`memory_resolve`、`query_memory`、`get_recent_digest` 三个工具，任何 OpenClaw Agent 可直接调用
- 不依赖 Pinecone / Neo4j，裸跑在 2C2G 服务器；6 级 markdown 可被运营/HR 直接编辑
- 代码入口：`core/flow_memory/`

### 第三志愿 · AI 大模型安全 · 课题一
**面向 Agent + 客户端环境下的安全操作与数据防护**

LarkMentor 的 `core/security/` 是一个独立可用的客户端安全中间件库（ShieldClaw），8 层防护全链路：
- **L1 PermissionManager**：5 级权限 deny-by-default，25 个工具精细授权
- **L2 TranscriptClassifier**：Prompt Injection 检测（regex + LLM judge 双层）
- **L3 HookSystem**：9 个生命周期事件的声明式拦截
- **L4 PIIScrubber**：7 类 PII 脱敏（手机/身份证/邮箱/银行卡/open_id 等），入库前 + LLM 调用前双扫
- **L5 KeywordDenylist**：高危词 + 正则热加载拦截
- **L6 RateLimiter**：60s 滑窗每用户限流
- **L7 ToolSandbox**：飞书 API allowlist，工具不能调用白名单外的接口
- **L8 AuditLog**：JSONL append-only 全链路审计，每次工具调用留痕
- Promptfoo 红队 **14/14 通过**，覆盖 OWASP LLM Top 10 全部威胁
- 代码入口：`core/security/`

---

## 功能详解

### Smart Shield · 消息守护

**工作流程**：

```
飞书消息到达
  → 8 层安全栈过滤（PII脱敏、注入检测等）
  → 6 维分类打分：
      身份维度 × 0.25（发送人是谁：老板/同事/广播机器人）
      关系维度 × 0.10（和我的历史互动频率）
      内容维度 × 0.30（有没有紧急词/截止日期）
      任务维度 × 0.15（和我当前项目的相关度）
      时间维度 × 0.10（今天/明天/下周？）
      频道维度 × 0.10（私聊/小群/大群广播？）
  → 加权得分 → P0/P1/P2/P3 分级
  → 专注期间：P0 立即推送，P2/P3 先攒着
  → 退出专注：弹出 Recovery Card
```

**分级说明**：

| 级别 | 分数 | 处理方式 | 典型场景 |
|------|------|----------|----------|
| P0 | ≥ 0.55 | 立即推送 + 自动起草回复 | 老板说"紧急：方案立刻确认" |
| P1 | ≥ 0.38 | 立即推送 | 同事问今天能给反馈吗 |
| P2 | ≥ 0.24 | 攒到专注结束再推 | 周五例会改到下午3点 |
| P3 | < 0.24 | 归档，Recovery Card 摘要展示 | FYI 行业新闻转发 |

> LLM 只在分数落在边界区间（±0.05）时才调用做最终仲裁，总调用率 < 12%，不会因为 API 慢影响主链路速度。

**Recovery Card（双线交点）**：

专注结束后，Bot 发出一张卡片：
- **上半张**（Shield 出品）：按 P0→P1→P2 排序，"我替你挡了这些，每条附带为什么这么分级"
- **下半张**（Mentor 出品）：针对最高优先级消息，自动起草 3 版回复（保守/中性/直接），点"采纳"复制到剪贴板，**Bot 不会自动发送**

### Mentor 4 Skills · 表达带教

**MentorWrite · 消息起草**

用 NVC（非暴力沟通）4 段诊断原始消息（事实/感受/需求/请求），按"对老板/对同事/对下属"3 档语气输出 3 版改写。

```
用户发：帮我看老板：好的我马上改

Bot 返回：
v1 保守：「好的张哥，我下午 2 点前给到你，有问题随时找我。」
v2 中性：「收到，我先看一下，预计今天内反馈。」
v3 直接：「好，今天给你。」
```

**MentorTask · 任务澄清**

LLM 对任务描述评估模糊度（0-1），>0.5 自动给出信息增益最高的 2 个澄清问题，帮你在接任务前问清楚。

```
用户发：任务确认：需要做个新功能

Bot 返回：
模糊度评分：0.85（高）
缺失维度：范围/截止时间/涉及人员/验收标准
建议问：
  Q1：这个功能的核心用户场景是什么，验收标准怎么定？
  Q2：截止时间是什么时候，有没有其他人需要配合？
```

**MentorReview · STAR 周报**

从飞书 IM 聊天记录、妙记会议纪要、任务系统自动提取本周内容，强制生成 STAR 结构周报（Situation/Task/Action/Result），每条 bullet 带 `[来源: archival_xxx]` 引用，点击可跳回原会话。

**MentorOnboard · 新人入职**

首次触发时一次性问 5 个问题（部门/直接对接人/团队回复期望/写作风格/最希望的帮助场景），答案存入个人知识库，后续所有 Mentor 草稿优先召回这份上下文。

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         接口层                                   │
│  飞书 Bot (WebSocket 长连接)  ·  MCP Server (HTTP/stdio)         │
│  Dashboard (FastAPI)  ·  Scheduler (定时日报/周报/日历轮询)      │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                         业务层                                   │
│                                                                  │
│  ┌── Smart Shield ──────────┐    ┌── Mentor 4 Skills ─────────┐ │
│  │  6 维分类 + LLM 边界仲裁  │    │  Write / Task / Review /   │ │
│  │  P0-P3 分级推送           │    │  Onboard                   │ │
│  │  Recovery Card (双线交点)  │◄──►│  永远是草稿，永不自动发    │ │
│  └──────────────────────────┘    └────────────────────────────┘ │
│                                                                  │
│  飞书 7 个 API：IM · Docx · Bitable · Calendar · Wiki · 妙记 · Reaction │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                         记忆层（FlowMemory）                     │
│  Working Memory (滑窗 200 事件)                                  │
│    → Compaction (LLM 摘要压缩)                                   │
│      → Archival (长期 SQLite 存储)                               │
│  flow_memory.md 6 级层次：Enterprise → Workspace → Dept         │
│                           → Group → User → Session              │
│  Knowledge Base：用户级 RAG（Doubao Embedding + BM25 兜底）     │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                         运行时（借鉴 Claude Code 7 支柱）         │
│  ToolRegistry · HookSystem · SkillLoader · PermissionManager    │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                         安全栈（8 层，全链路必经）                │
│  L1 Permission → L2 Inject → L3 Hook → L4 PII                  │
│  → L5 Denylist → L6 RateLimit → L7 Sandbox → L8 Audit          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 本地运行（5 分钟）

> **前提**：需要有飞书账号，并在飞书开发者平台创建应用（见下一节）。Python 3.10+ 即可，不需要 GPU，不需要任何额外服务。

### 第 1 步：克隆代码

```bash
git clone https://github.com/bcefghj/larkmentor.git
cd larkmentor
```

### 第 2 步：创建虚拟环境并安装依赖

```bash
# 创建虚拟环境（隔离依赖，不污染系统 Python）
python3 -m venv .venv

# 激活虚拟环境
# macOS / Linux：
source .venv/bin/activate
# Windows：
# .venv\Scripts\activate

# 安装依赖（只有 8 个包，很快）
pip install -r requirements.txt
```

### 第 3 步：配置环境变量

```bash
# 复制模板
cp .env.example .env

# 用任意编辑器打开 .env，填入以下内容：
# FEISHU_APP_ID=cli_xxxxxxxxx        ← 飞书开放平台获取
# FEISHU_APP_SECRET=xxxxxxxx          ← 飞书开放平台获取
# ARK_API_KEY=ark-xxxxxxxxxxxx        ← 火山方舟获取
# ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
# ARK_MODEL=doubao-seed-2.0-pro
```

> 不知道去哪里拿这些 Key？见 [FEISHU_SETUP.md](FEISHU_SETUP.md)（一步一步截图说明）。

### 第 4 步：运行测试（验证环境）

```bash
PYTHONPATH=. pytest tests/ -q --ignore=tests/e2e --ignore=tests/simulator
```

预期输出：

```
178 passed in 12.3s
```

> 如果 pytest 找不到，运行 `pip install pytest` 后重试。

### 第 5 步：启动 Bot

```bash
python main.py
```

启动成功会看到：

```
╔═══════════════════════════════════════════╗
║  LarkMentor – 消息守护 + 表达引导            ║
║  Smart Shield · Mentor · MCP · FlowMemory    ║
╚═══════════════════════════════════════════╝
正在连接飞书长连接服务...
连接成功后，在飞书中搜索 LarkMentor 机器人开始使用
```

然后打开飞书，搜索你创建的 Bot 名称，私聊发 `开启新人模式`，应该收到欢迎卡片。

### 第 6 步（可选）：启动 Dashboard 和 MCP Server

新开两个终端窗口（记得先 `source .venv/bin/activate`）：

```bash
# 终端 2：Dashboard 数据面板（浏览器打开 http://localhost:8001）
PYTHONPATH=. uvicorn dashboard.server:app --host 0.0.0.0 --port 8001

# 终端 3：MCP Server（供 Cursor/Claude Code 等 Agent 调用）
PYTHONPATH=. python -m core.mcp_server.server --transport http --port 8767
```

---

## 飞书开发者平台配置

> 完整步骤见 **[FEISHU_SETUP.md](FEISHU_SETUP.md)**，这里是 5 步摘要。

**第 1 步**：打开 https://open.feishu.cn/app → 创建自建应用 → 拿到 `App ID` 和 `App Secret`

**第 2 步**：左侧「应用功能」→「机器人」→ 开启机器人（消息卡片请求网址**留空**，用 WebSocket）

**第 3 步**：左侧「权限管理」→ 申请以下权限：

| 权限 | 用途 |
|------|------|
| `im:message` | 收发消息 |
| `im:message:send_as_bot` | Bot 主动发卡片 |
| `im:chat:readonly` | 读群信息 |
| `contact:user.base:readonly` | 识别发送者姓名 |
| `docx:document` | 创建成长记录文档 |
| `bitable:app` | 读写多维表格 |

**第 4 步**：左侧「开发配置」→「事件与回调」→ 选「**长连接**」→ 订阅：
- `im.message.receive_v1`（接收消息）
- `card.action.trigger`（卡片按钮点击，**必须订阅，否则 Recovery Card 的采纳按钮没反应**）

**第 5 步**：左侧「应用发布」→「版本管理与发布」→ 创建版本 → 提交（每次改权限后都要做这步）

---

## 服务器部署（阿里云 v2）

> v2 部署引入 Agent-Pilot 后端 + Sync WebSocket。一行命令：
>
> ```bash
> bash deploy/deploy_v2.sh
> ```
>
> 会自动（1）本地跑 pytest → （2）打包 → （3）scp 上传 → （4）远端建 venv、装依赖 → （5）创建/更新 3 个 systemd 服务：`larkmentor-v2` / `larkmentor-v2-dashboard` / `larkmentor-v2-mcp` →（6）更新 nginx 反代（含 `/sync/` WebSocket upgrade）→（7）冷切换 + 14 项 smoke test，失败自动回滚。

### v1 旧部署（作为参考）

> 如果只是想在本地试用，跳过这节。这节是给想把 Bot 7×24 跑在服务器上的人看的。

### 服务器要求

| 项目 | 最低要求 | 推荐 |
|------|----------|------|
| 操作系统 | Ubuntu 20.04+ | Ubuntu 22.04 |
| CPU | 2 核 | 2 核 |
| 内存 | 2 GB | 4 GB |
| 磁盘 | 20 GB | 40 GB |
| 网络 | 需要开放 80 / 8001 / 8767 端口 | — |

### 一键部署

在本地仓库目录执行：

```bash
cd deploy
bash deploy_lark_mentor.sh
```

脚本会自动完成以下所有步骤（无需手动操作服务器）：

```
Step 0：本地跑全量 pytest，有任何测试失败则中止部署
Step 1：把代码打包成 .tar.gz（排除 data/ .venv/ .env 等）
Step 2：通过 scp 上传压缩包到服务器 /opt/larkmentor_release.tar.gz
Step 3：服务器端操作：
        - 备份旧版数据（user_states.json / 知识库 / 记忆等）
        - 解压到 /opt/larkmentor/
        - 从旧版复制 .env 和持久化数据（无缝迁移）
        - 创建 Python 虚拟环境，安装依赖
        - 写入 3 个 systemd 服务配置文件
Step 4：冷切换：停旧服务 → 启新服务
Step 5：验证 nginx 配置
Step 6：运行 smoke_test.sh（15 项检查），任何一项失败自动回滚
```

部署成功后，访问 http://你的服务器IP/ 查看主页。

### 部署后运行的 3 个服务

| systemd 服务名 | 端口 | 说明 |
|----------------|------|------|
| `larkmentor.service` | — | 飞书 Bot 主进程（WebSocket 长连接，不需要端口） |
| `larkmentor-dashboard.service` | 8001 | Web 数据面板 |
| `larkmentor-mcp.service` | 8767 | MCP HTTP Server |

### 常用运维命令

```bash
# 查看 Bot 运行状态
systemctl status larkmentor

# 查看实时日志
journalctl -u larkmentor -f

# 重启服务
systemctl restart larkmentor

# 一键回滚到上一个版本（< 60 秒）
cd deploy && bash rollback.sh

# 验证服务健康
bash deploy/smoke_test.sh
```

### Nginx 反向代理配置参考

```nginx
server {
    listen 80;
    server_name 你的域名或IP;

    # 主页（静态文件）
    location / {
        root /opt/larkmentor/website;
        index index.html;
        try_files $uri $uri/ =404;
    }

    # Dashboard
    location /dashboard {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
    }

    # MCP API
    location /mcp/ {
        proxy_pass http://127.0.0.1:8767/;
    }

    # 健康检查
    location /health {
        proxy_pass http://127.0.0.1:8001/health;
    }
}
```

---

## 使用指令大全

在飞书中和 Bot 私聊，发送以下指令：

### v2 Agent-Pilot（IM → Doc → PPT 闭环）

| 指令 | 效果 |
| --- | --- |
| `/pilot <自然语言>` | 启动 Agent-Pilot DAG，自动生成 Doc/Canvas/PPT 并四端同步 |
| `pilot` / `/pilot` / `飞行员` | 查看 /pilot 用法说明 |
| `我的飞行员` / `pilot 列表` | 查看最近 8 次 Pilot 运行 |

在群聊里 @LarkMentor 也支持（不需要开启专注模式），示例：

```
@LarkMentor /pilot 把今天的讨论做成评审 PPT
```

### 消息守护（Smart Shield）

| 指令 | 效果 |
|------|------|
| `专注开` / `专注 90 分钟` | 进入勿扰模式，低优先级消息被拦截 |
| `专注关` | 退出勿扰，弹出 Recovery Card（显示被拦截的消息 + AI 草稿回复） |
| `状态` | 查看当前守护状态、已勿扰多久、白名单 |
| `日报` | 今日守护与协作摘要 |
| `周报` | 周度复盘简报（STAR 结构） |
| `记忆` | 查看组织语境与工作记忆 |

### 表达引导（Mentor）

| 指令 | 效果 |
|------|------|
| `@Mentor 你的问题` | 自动路由到对应 Mentor 技能（写作/任务/复盘/入职） |
| `帮我看看：<消息内容>` | 消息措辞审核，给出 3 版不同语气的改写 |
| `帮我看老板：<消息内容>` | 同上，语气对应「对上级」 |
| `任务确认：<任务描述>` | 评估任务模糊度，给出最应该问清楚的 2 个问题 |
| `写周报：内容` | 生成 STAR 格式周报草稿 |
| `开启新人模式` | 触发入职 5 问，答案存入个人知识库 |

> 所有 AI 输出均为草稿，需确认后发送，Bot 永远不会替你自动发消息。

### 知识库管理

| 指令 | 效果 |
|------|------|
| `导入文档：<文本内容>` | 将文本存入组织知识库（后续 Mentor 会优先参考） |
| `导入wiki：<Wiki 链接>` | 从飞书 Wiki 页面抓取内容存入知识库 |
| `查询知识：<关键词>` | 在知识库中搜索 |
| `知识库列表` | 查看已有知识 |

### 白名单与设置

| 指令 | 效果 |
|------|------|
| `白名单 张三` | 将"张三"加入白名单，勿扰时其消息直通 |
| `移除白名单 张三` | 从白名单移除 |
| `白名单列表` | 查看当前白名单 |
| `删除我的数据` | 物理删除账号下所有数据（不可恢复） |

---

## 代码结构

```
larkmentor/
│
├── main.py                      # 主入口：启动飞书 WebSocket 长连接 + 定时任务
├── config.py                    # 从 .env 读取所有配置（阈值/权重/端口等均可调）
├── requirements.txt             # 依赖（8 个包：lark-oapi/openai/fastapi/rank-bm25 等）
├── .env.example                 # 环境变量模板，复制后填入真实值
├── larkmentor_report.pdf        # 完整技术报告（含架构图/算法说明/安全分析）
│
├── bot/                         # 飞书 Bot 接口层
│   ├── event_handler.py         #   核心：消息事件分发 + 卡片按钮回调处理
│   ├── feishu_client.py         #   飞书 API 客户端（Token 管理/请求封装）
│   ├── message_sender.py        #   消息发送工具（文本/卡片/加急）
│   └── card_builder.py          #   飞书交互卡片 JSON 构建
│
├── core/                        # 核心业务逻辑
│   ├── smart_shield.py          #   Smart Shield 主链路（消息进来的第一道门）
│   ├── smart_shield_v3.py       #   v3 增强链路（8 层安全栈全部经过）
│   ├── classification_engine.py #   6 维消息分类引擎（规则 + LLM 仲裁）
│   ├── recovery_card.py         #   Recovery Card 构建（双线产品的唯一交点）
│   ├── sender_profile.py        #   发件人画像（学习历史互动，动态调整权重）
│   ├── analytics.py             #   日报/周报统计分析
│   ├── notification_channels.py #   多渠道通知（邮件/Bark/Server酱）
│   │
│   ├── mentor/                  #   Mentor 4 Skills（表达层带教）
│   │   ├── mentor_write.py      #     MentorWrite：NVC 框架消息起草
│   │   ├── mentor_task.py       #     MentorTask：任务模糊度评估 + 澄清问题
│   │   ├── mentor_review.py     #     MentorReview：STAR 结构周报生成
│   │   ├── mentor_onboard.py    #     MentorOnboard：新人入职 5 问
│   │   ├── knowledge_base.py    #     用户级 RAG 知识库（Doubao Embedding + BM25）
│   │   ├── mentor_router.py     #     根据指令路由到对应 Skill
│   │   ├── proactive_hook.py    #     主动出手频控（避免过度打扰）
│   │   ├── growth_doc.py        #     成长档案：自动生成飞书 Docx
│   │   └── skills_init.py       #     Skill 注册初始化
│   │
│   ├── runtime/                 #   运行时基础设施（借鉴 Claude Code 7 支柱）
│   │   ├── tool_registry.py     #     ToolRegistry：18 个 MCP 工具统一注册
│   │   ├── hook_runtime.py      #     HookSystem facade：9 个生命周期事件
│   │   ├── skill_loader.py      #     SkillLoader：Skill 元数据 + 动态加载
│   │   └── permission_facade.py #     PermissionManager facade
│   │
│   ├── security/                #   安全栈（对应赛道三：ShieldClaw 中间件）
│   │   ├── permission_manager.py   # L1：5 级权限 deny-by-default
│   │   ├── transcript_classifier.py# L2：Prompt Injection 检测
│   │   ├── hook_system.py          # L3：9 个生命周期事件拦截
│   │   ├── pii_scrubber.py         # L4：7 类 PII 脱敏
│   │   ├── keyword_denylist.py     # L5：高危词 + 正则热加载
│   │   ├── rate_limiter.py         # L6：60s 滑窗限流
│   │   ├── tool_sandbox.py         # L7：飞书 API allowlist 沙箱
│   │   └── audit_log.py            # L8：JSONL append-only 全链路审计
│   │
│   ├── flow_memory/             #   FlowMemory 记忆引擎（对应赛道二）
│   │   ├── working.py           #     Working Memory：当前会话滑窗 200 事件
│   │   ├── compaction.py        #     Compaction：LLM 摘要压缩，保留关键信息
│   │   ├── archival.py          #     Archival：长期 SQLite 归档 + 检索
│   │   └── flow_memory_md.py    #     6 级层次 resolver：Enterprise→Session 合并
│   │
│   ├── feishu_advanced/         #   飞书 7 个 API 的高级封装
│   │   ├── calendar_busy.py     #     日历：查询忙闲时段
│   │   ├── wiki_search.py       #     Wiki：知识检索和导入
│   │   ├── minutes_fetch.py     #     妙记：拉取会议纪要（周报用）
│   │   ├── reaction_api.py      #     Reaction：已读回执
│   │   ├── reply_thread.py      #     话题回复：在原消息线程回复
│   │   ├── task_v2.py           #     飞书任务 v2
│   │   └── urgent_api.py        #     加急通知
│   │
│   ├── mcp_server/              #   MCP 协议 Server（对外暴露 21 个工具）
│   │   ├── server.py            #     HTTP + stdio 双传输模式
│   │   └── tools.py             #     工具定义：shield/mentor/memory/skill/pilot
│   │
│   ├── agent_pilot/             #   v2 Agent-Pilot 核心（Scenario A-F 编排）
│   │   ├── planner.py           #     Scenario B: Doubao LLM + Heuristic DAG planner
│   │   ├── orchestrator.py      #     DAG 执行器（thread pool parallel groups）
│   │   ├── scenarios.py         #     6 场景注册
│   │   ├── advanced.py          #     主动澄清 / 讨论总结 / 下一步推荐
│   │   ├── service.py           #     Process-wide 单例 + 持久化
│   │   └── tools/
│   │       ├── doc_tool.py      #     Scenario C: 飞书 Docx 创建/追加
│   │       ├── canvas_tool.py   #     Scenario C: tldraw + 飞书画板双写（富媒体）
│   │       ├── slide_tool.py    #     Scenario D: Slidev → pptx + 演讲稿
│   │       ├── voice_tool.py    #     Scenario A: Doubao/妙记 STT
│   │       ├── archive_tool.py  #     Scenario F: 汇总打包 + 分享链接
│   │       ├── im_tool.py       #     Scenario A: im.fetch_thread 上下文
│   │       └── mentor_tool.py   #     Advanced: mentor.clarify / summarize
│   │
│   ├── sync/                    #   v2 多端同步层（Scenario E）
│   │   ├── crdt_hub.py          #     Yjs y-py Hub + WebSocket 广播
│   │   ├── ws_server.py         #     /sync/ws FastAPI 路由
│   │   └── offline_merge.py     #     离线合并对账
│   │
│   └── work_review/             #   工作回顾
│       ├── weekly_report.py     #     周报：STAR 结构 + 引用追踪
│       └── monthly_wrapped.py   #     月报：数据汇总
│
├── llm/                         # LLM 调用层
│   ├── llm_client.py            #   OpenAI 兼容客户端（火山方舟 Doubao）
│   └── prompts.py               #   所有 Prompt 模板（集中管理，方便调试）
│
├── memory/                      # 持久化存储
│   ├── user_state.py            #   用户状态（focus/whitelist/rookie_mode）
│   ├── context_snapshot.py      #   上下文快照（进入专注前自动保存）
│   └── interruption_log.py      #   打断日志（用于统计和分析）
│
├── dashboard/                   # Web 数据面板
│   ├── server.py                #   FastAPI 服务（v3 API + v4 Mentor Stats）
│   ├── mentor_stats.py          #   Mentor 使用统计 API
│   └── static/                  #   前端页面（HTML/CSS/JS）
│
├── utils/                       # 工具函数
│   ├── feishu_api.py            #   飞书底层 API 封装（Token/请求/重试）
│   └── time_utils.py            #   时间处理工具
│
├── tests/                       # 测试套件
│   ├── test_smart_shield.py     #   Smart Shield 6 维分类测试
│   ├── test_mentor.py           #   Mentor 4 Skills 端到端测试
│   ├── test_recovery_card.py    #   Recovery Card 构建测试
│   ├── test_runtime.py          #   ToolRegistry/HookSystem 测试
│   ├── test_security_stack.py   #   8 层安全栈测试
│   ├── test_security_new_layers.py # 新增安全层测试
│   ├── test_flow_memory.py      #   FlowMemory 三层测试
│   ├── test_knowledge_base.py   #   知识库 + 用户隔离测试
│   ├── test_mcp_and_review.py   #   MCP 工具 + 周报测试
│   ├── test_concurrency.py      #   并发安全测试
│   └── simulator/               #   场景模拟测试
│       └── scenarios/           #   12 个 YAML 场景（紧急词/白名单/闲聊/边界等）
│
├── mobile_desktop/              # v2 Flutter 4-in-1 客户端（iOS/Android/macOS/Windows）
│   ├── lib/
│   │   ├── main.dart
│   │   ├── screens/             #   pilot_home / doc_view / canvas_view / slide_view / voice_input / settings
│   │   ├── services/            #   sync_service (Yjs WS) / api_service / voice_service / offline_cache
│   │   └── ...
│   ├── pubspec.yaml
│   └── README.md                #   构建/运行/打包说明
│
└── deploy/                      # 部署脚本
    ├── deploy_lark_mentor.sh    #   v1 一键部署
    ├── deploy_v2.sh             #   v2 一键部署（含 pytest + 14 项 smoke test + 自动回滚）
    ├── smoke_test_v2.sh         #   v2 部署后健康检查
    ├── rollback.sh              #   一键回滚（< 60 秒）
    └── smoke_test.sh            #   v1 smoke
```

---

## 量化指标

| 指标 | 数值 | 说明 |
|------|------|------|
| Python 文件 | 100+ 个 | v2 新增 `core/agent_pilot/` + `core/sync/` + 相关 tools |
| 代码行数 | 16,000+ 行 | v2 新增 ~1,800 行后端 + ~1,300 行 Flutter Dart |
| pytest 用例 | **218 个，全部通过** | v2 新增 40 条 agent_pilot/sync/advanced/api 测试 |
| Promptfoo 红队 | **14/14 通过** | 覆盖 OWASP LLM Top 10 |
| 6 维分类准确率 | **99%** | 102 个 YAML 场景测试集 |
| LLM 调用率 | **< 12%** | 规则短路，边界才调 LLM |
| 规则路径 P99 延迟 | **< 80ms** | 不含网络时延 |
| LLM 路径 P99 延迟 | **< 2.2s** | 含 Doubao API 调用 |
| MCP 工具数 | **21 个** | v1 的 18 个 + v2 新增 `pilot_launch / pilot_status / pilot_list` |
| 飞书 API 接入 | **7 个** | IM/Docx/Bitable/Calendar/Wiki/Minutes/Reaction |
| Flutter 目标端 | **4 端** | iOS / Android / macOS / Windows 一套代码 |
| Agent-Pilot 场景覆盖 | **A-F 全 6 场景** | `core/agent_pilot/scenarios.py` 统一注册 |
| 安全栈层数 | **8 层** | 全链路必经，无快速路径 |
| 部署成本 | **2C2G 起** | 阿里云最低规格，systemd × 3 服务 |

---

## 技术选型说明

| 组件 | 选型 | 为什么这么选 |
|------|------|-------------|
| 飞书 SDK | `lark-oapi` | 官方 SDK，支持 WebSocket 长连接，本地开发不需要公网 IP |
| LLM | 火山方舟 Doubao | OpenAI 兼容 API，Coding Plan 用户免费额度，国内延迟低 |
| Embedding | Doubao Embedding | 与 LLM 同一个 API Key，2048 维，无需额外账号 |
| 检索兜底 | `rank-bm25` | 纯 Python，Embedding API 挂了自动降级，永不中断 |
| Web | FastAPI + Uvicorn | Dashboard + MCP Server，性能够用，部署简单 |
| 调度 | APScheduler | 日报/周报/日历轮询/Profile 衰减，无需额外 Redis |
| 存储 | SQLite + JSON | 单文件，2C2G 友好，不需要搭 PostgreSQL/Redis |

**为什么不用 LangGraph / CrewAI / LangChain？**

- LangGraph 写一个简单 ReAct 需要 120 行；我们用纯 prompt + Python router 只需要 89 行，更可读、更可审计
- 这些框架依赖重，2C2G 服务器内存不够
- 遵循 Anthropic Claude Code 的工程哲学：纯 prompt + Python facade，不引入魔法框架

---

## 团队

| 成员 | 角色 | 联系 |
|------|------|------|
| [戴尚好](https://bcefghj.github.io) | 全栈开发 / Agent 安全 / 服务器部署 / 答辩 | [bcefghj@163.com](mailto:bcefghj@163.com) |
| [李洁盈](https://janeliii.netlify.app/) | 产品设计 / UI/UX / 内容运营 / 演讲 | [JieyingLiii@outlook.com](mailto:JieyingLiii@outlook.com) |

---

## License

[MIT License](LICENSE) · Copyright © 2026 戴尚好 & 李洁盈
