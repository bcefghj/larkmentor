# Agent-Pilot V1 · 裁判 5 分钟验收指南

> 让裁判 5 分钟内完成 **设计 → 跑通 → 看产物 → 打分** 全流程。

---

## 准备（< 30 秒）

可选三种方式之一：

- **A 选项（推荐）公网 Demo**
  - 主页：[http://8.136.98.175/](http://8.136.98.175/) — 全新动画首页
  - 仪表盘：[http://8.136.98.175/dashboard](http://8.136.98.175/dashboard)
  - 多端协同：[http://8.136.98.175/multi-end](http://8.136.98.175/multi-end)
  - API 文档：[http://8.136.98.175/docs](http://8.136.98.175/docs)
  - MCP 反向暴露：`http://8.136.98.175/mcp/`（接 Cursor / Claude / Trae）
  - 健康：[http://8.136.98.175/health](http://8.136.98.175/health) → `{"status":"healthy","version":"v1.0.0"}`

- **B 选项 飞书机器人** — 加好友 `Agent-Pilot`（同 IP 长连接，二维码见 README）

- **C 选项 本地 5 分钟搭建**
  ```bash
  git clone https://github.com/bcefghj/Agent-Pilot.git -b v1-rewrite
  cd Agent-Pilot
  python3.10 -m venv .venv && source .venv/bin/activate
  pip install -e ".[dev]"
  python -m pilot dashboard            # 本地 :8001
  ```

---

## 第 1 个 30 秒 · 发一条文本消息

在飞书 Bot 里发：

> `帮我写一份关于 AI Agent 发展趋势的报告`

**预期** 立刻收到回复（< 3 秒）：

```
🛫 Agent-Pilot V1 已启动
Plan: plan_xxxxxxx_xxxxxx
意图：帮我写一份关于 AI Agent 发展趋势的报告

📋 计划（共 3 步）：
  1. [doc.create] 创建飞书 Docx 文档
  2. [doc.append] 向文档追加 AI 自动生成的详细内容
  3. [archive.bundle] 汇总产物，生成飞书分享链接

实时进度：http://8.136.98.175/dashboard?plan_id=plan_xxx
```

**裁判可立刻打开实时面板**，看到 8 步 Claude Code Harness Loop 的高亮进度。

---

## 第 2 个 30 秒 · 模糊意图 → 主动澄清（修复 v13 P0）

发：

> `帮我做个汇报`

**预期** 收到一张 **橙色澄清卡**（标题"🤔 Agent-Pilot · 主动澄清"）：

| 按钮 | 行为 |
|---|---|
| 生成文档 | 自动展开为"…（请生成方案文档）"重新启动 |
| 生成 PPT | 自动展开为"…（请生成 PPT）"重新启动 |
| 文档 + PPT 三件套 | 自动展开为"…（请生成文档 + 架构图 + PPT 三件套）" |
| 跳过，直接开始 | 用原意图启动 |

**裁判需检查**：4 个按钮**任意一个**点击后都能继续推进（v13 此处全部失效，V1 修复）。

---

## 第 3 个 30 秒 · 三件套（doc + canvas + slide）

发：

> `产品方案 + 架构图 + 评审 PPT 三件套`

**预期** 最多 90 秒后收到 **3 种产物链接**：

- 📄 飞书 Docx（方案文档，1500+ 字）
- 🎨 画布（含 tldraw 节点 JSON + Mermaid 流程图代码）
- 📊 PPT（**真 .pptx 文件**，可下载用 Keynote/PowerPoint 打开）

**裁判检查**：
- ✅ 下载 `.pptx`，6+ 页幻灯片，每页有标题 + 要点 + 演讲备注
- ✅ Canvas 文档里的 Mermaid 代码在飞书 Docx 里渲染成流程图
- ✅ 三个产物的核心内容**一致**（围绕"产品方案"主题）

---

## 第 4 个 30 秒 · 多端协同

打开两个端：
1. 手机飞书 IM 中触发任务
2. 电脑浏览器打开 [http://8.136.98.175/multi-end](http://8.136.98.175/multi-end)

观察：
- ✅ 两端同时显示任务进度更新
- ✅ Web 端的事件流与飞书卡片状态一致
- ✅ WebSocket 实时打印每步 step.done 事件
- ✅ Presence 在线状态实时更新

如果还有 Flutter 客户端：
```bash
cd flutter_client && flutter run -d chrome \
  --dart-define=AGENT_PILOT_BASE_URL=http://8.136.98.175
```
打开后切到「多端」页，输入相同 room_id，观察三端同步。

---

## 第 5 个 30 秒 · MCP 反向暴露（创新点）

V1 把自己暴露为 **MCP server**，让 Cursor / Claude / Trae 反向调用：

```bash
# 列出 V1 提供的工具
curl http://8.136.98.175/mcp/tools/list

# 反向调用 doc.create
curl -X POST http://8.136.98.175/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name": "doc.create", "arguments": {"title": "评委创建的文档"}}'
```

返回的 doc_token + url 可直接在飞书或 Dashboard 中查看。

---

## 第 6 个 30 秒 · 5 层 Harness 架构验证

[http://8.136.98.175/](http://8.136.98.175/) 主页含 5 层架构 + 8 步 loop 动画图。

```bash
# 看工具清单（按 read/write 分类）
curl http://8.136.98.175/api/tools

# 看实时 sessions
curl http://8.136.98.175/api/sessions
```

---

## 评分参考

按 [项目评分维度](#)：

### 维度 1：完整性与价值（50%）

- ✅ 端到端闭环：IM → 三闸门 → Planner → 4 工具 → 归档
- ✅ Demo 稳定：7 条裁判级 e2e 用例 0.3 秒跑完，门控 30 秒
- ✅ 全程 < 90 秒（v13 是 360 秒）
- ✅ 解决真实痛点：从对话直接到可交付的专业产物

### 维度 2：创新性（25%）

- ✅ **5 层 Harness 架构**（Modern Agent Harness Blueprint 2026）
- ✅ **Claude Code 8 步 harness loop** 内核
- ✅ **Anthropic 三 Agent GAN harness**（Planner/Generator/Evaluator + Sprint 合约）
- ✅ **MCP 反向暴露**：让 Cursor/Claude/Trae 反过来调 V1
- ✅ **CardKit 2.0 70ms 打字机** 流式卡片
- ✅ **Cognition 单线程写**：Researcher/Critic 只读、Writer 独占
- ✅ **lark-cli 29 SKILL.md** 体系（飞书官方背书）
- ✅ **PRD §5/§7 任务卡片 + 上下文包**

### 维度 3：技术实现性（25%）

- ✅ **5 层单向依赖**：Surface → Runtime → Context/Capability/Governance
- ✅ **75+ 单元 + e2e 测试全绿**
- ✅ **CRDT 多端同步**（pycrdt-websocket + 离线 reconcile）
- ✅ **4 级权限网关**（deny → allow → classifier → ask）
- ✅ **OpenTelemetry tracing** 可选启用
- ✅ **append-only event log** + filesystem working memory（artifact handle）

---

## 进阶验证（可选）

```bash
# 在我们的服务器上跑端到端测试
ssh root@8.136.98.175 \
  "cd /opt/agent-pilot && PYTHONPATH=. .venv/bin/python -m pytest tests/ -v"
# 75/75 passed in < 2 秒
```

### 看代码（5 层 Harness）

| 层 | 路径 |
|---|---|
| Runtime | [`pilot/runtime/harness.py`](../pilot/runtime/harness.py) |
| Context | [`pilot/context/event_log.py`](../pilot/context/event_log.py) |
| Capability | [`pilot/capability/tools/registry.py`](../pilot/capability/tools/registry.py) |
| Governance | [`pilot/governance/policy.py`](../pilot/governance/policy.py) |
| Surface | [`pilot/surface/feishu/router.py`](../pilot/surface/feishu/router.py) |

### 一键回滚（如出问题）

```bash
ssh root@8.136.98.175
systemctl stop agent-pilot-bot agent-pilot-dashboard
mv /opt/agent-pilot /opt/agent-pilot-v1-failed
tar xzf /var/backups/agent-pilot-v13-pre-v1-*.tar.gz -C /
systemctl start agent-pilot-v13-bot agent-pilot-v13-dashboard
```

---

## 联系

- 戴尚好（bcefghj@163.com）
- 李洁盈（JieyingLiii@outlook.com）
- GitHub: https://github.com/bcefghj/Agent-Pilot
