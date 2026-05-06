# 🛬 Agent-Pilot v13 · 裁判 5 分钟验证指南

> 目标：让裁判在 5 分钟内完成"设计 → 跑通 → 看产物 → 打分"全流程。

---

## 准备（< 30 秒）

需要至少其一：
- **A 选项（最快，推荐）**：直接打开公网 Demo
  - 多端协同监控：[http://118.178.242.26/v13/multi-end](http://118.178.242.26/v13/multi-end)
  - Pilot 仪表盘：[http://118.178.242.26/dashboard/pilot](http://118.178.242.26/dashboard/pilot)
- **B 选项**：飞书加机器人 `Agent-Pilot`（同 IP 部署，二维码见 README）
- **C 选项**：本地 5 分钟搭建（见 README "快速开始"）

---

## 第 1 个 30 秒：发一条文本消息

在飞书 Bot 里发：

> `帮我写一份关于 AI Agent 发展趋势的报告`

你会**立刻**收到回复（≤ 3 秒）：

```
🛫 Agent-Pilot 已启动
Plan: plan_xxxxxxx_xxxxxx
意图：帮我写一份关于 AI Agent 发展趋势的报告

📋 计划（共 4 步）：
  1. doc.create — 创建飞书 Docx
  2. doc.append — AI 自动生成详细内容
  3. archive.bundle — 汇总并生成分享链接
  ...

实时进度：http://118.178.242.26/dashboard/pilot?plan_id=xxx
```

➡️ **此刻可以打开实时进度面板**，看到 4-Agent 工坊（Researcher → Writer → Critic → Presenter）逐步推进。

---

## 第 2 个 30 秒：等待与观察（约 60-150 秒）

打开 [/v13/multi-end](http://118.178.242.26/v13/multi-end)，输入 plan_id，点击 "Join Room"。会看到：

| 区域 | 应当出现 |
|------|---------|
| 任务状态 | 步骤 1/N → 2/N → ... → N/N，每步 status 从 `pending` → `running` → `done` |
| 4-Agent trace | Researcher → Writer → Critic → Presenter，每个有耗时 + 输出摘要 |
| 产物清单 | 飞书 Docx URL、(若有) PPTX URL、tldraw URL |
| WebSocket 事件流 | 每步 done 都会推一条 `{"kind": "event", ...}` |

---

## 第 3 个 30 秒：检查产物（最关键）

完成后飞书发回完成通知：

```
🛬 Agent-Pilot 任务完成
plan_xxx · 4/4 步完成

📝 内容摘要：
AI Agent（人工智能代理）作为大语言模型能力跃迁的核心应用形态...

📦 产物链接：
  • 📄 飞书文档：https://rcnqvnspd31b.feishu.cn/docx/HoVIdElmLoFzRFx5zCcciiutnKd
  • 🔗 分享链接：[Agent-Pilot] 汇报摘要 · plan_xxx

📊 进度面板：http://118.178.242.26/dashboard/pilot?plan_id=xxx
```

**裁判检查**：
- ✅ 飞书 Docx 链接打开 → 应该是真文档，不是空白
- ✅ 文档至少 1500+ 字（实测真 LLM 跑出 7800+ 字）
- ✅ 文档结构完整：概述 / 背景 / 核心内容 / 案例 / 风险 / 结论
- ✅ 内容有数据、有案例（如"全球 AI Agent 市场预计从 2024 年的约 54 亿美元增长至 2030 年的超过 216 亿美元"）

---

## 第 4 个 30 秒：跑三件套（doc + canvas + ppt）

发：

> `产品方案 + 架构图 + 评审 PPT 三件套`

完成后会收到 **3 种产物链接**：
- 📄 飞书 Docx（方案文档）
- 🎨 画布（包含 Mermaid 流程图 + tldraw 节点）
- 📊 PPT（**真 .pptx 文件**，可下载用 Keynote/PowerPoint 打开）

**裁判检查**：
- ✅ 下载 `.pptx`，用 Keynote 打开，应有 6+ 页幻灯片，每页有标题 + 3-5 条要点 + 演讲备注
- ✅ Canvas 文档里的 Mermaid 代码块在飞书 Docx 里会自动渲染成流程图
- ✅ 三个产物的核心内容**一致**（都围绕"产品方案"这个主题）

---

## 第 5 个 30 秒：模糊意图触发主动澄清

发：

> `帮我做个汇报`

应当看到 Agent 回复一条 **mentor.clarify 卡片**，问：
- 汇报对象是谁？
- 希望生成文档还是 PPT？
- 期望页数？
- 是否需要引用已有资料？

➡️ 这验证了 PRD §5.3 的"信息不足时主动澄清"。

---

## 第 6 个 30 秒：多端同步演示

打开两个端：
1. 手机飞书 IM 中触发任务
2. 电脑浏览器打开 `/v13/multi-end`

观察：
- ✅ 两端同时显示任务进度更新
- ✅ Web 端的 4-Agent trace 与飞书卡片状态一致
- ✅ WebSocket 事件流实时打印每步 step.done 事件

---

## 评分参考

按 [项目评分维度](#) 的 3 大维度核查：

### 维度 1：完整性与价值（50%）
- ✅ 端到端闭环：IM → 意图识别 → 规划 → 4-Agent 协作 → 产物 → 归档
- ✅ Demo 稳定：5/5 测试用例自动化通过（见 [scripts/judge_demo.py](../scripts/judge_demo.py)）
- ✅ 全程 < 3 分钟（mocked），真 LLM 文档生成约 1-5 分钟
- ✅ 解决真实痛点：从对话直接到可交付的专业产物

### 维度 2：创新性（25%）
- ✅ **4-Agent 协作工坊**（Researcher / Writer / Critic / Presenter）
- ✅ **PPT 三件套**（.pptx + Slidev HTML + TTS mp3）
- ✅ **流式打字机卡片**（cardkit patch）
- ✅ **三闸门主动识别 + 主动澄清**（PRD §5）
- ✅ **PRD §5/§7 任务卡片 + 上下文包**（行业内独有的执行前确认机制）

### 维度 3：技术实现性（25%）
- ✅ 模块化架构：`agent_pilot/{runtime,tools,intel,io,llm}/` 单向依赖
- ✅ 鲁棒错误处理：429 指数退避、JSON 解析多策略、单次重试机制
- ✅ 测试覆盖：5 条裁判级别用例 + 自动 visual inspect + HTML 报告
- ✅ 多端 CRDT：WebSocket Hub + Yjs y-py + 离线合并对账
- ✅ 监控：Prometheus metrics + structured_logging + DAG trace

---

## 进阶验证（可选）

### 自己跑端到端测试

```bash
# 在我们的服务器上执行（无需登录飞书）
ssh root@118.178.242.26
cd /opt/agent-pilot-v13
python3 scripts/judge_demo.py --real
# 报告会落到 data/test_reports/{ts}/index.html
```

### 看代码

- 4-Agent 实现：[agent_pilot/intel/multi_agent.py](../agent_pilot/intel/multi_agent.py)
- 真 PPTX 生成：[agent_pilot/tools/slide.py](../agent_pilot/tools/slide.py)
- 任务卡片：[agent_pilot/io/feishu/cards/task_card.py](../agent_pilot/io/feishu/cards/task_card.py)
- 状态机：[agent_pilot/runtime/state_machine.py](../agent_pilot/runtime/state_machine.py)

### 一键回滚（如出问题）

```bash
# 恢复 v12 版本
ssh root@118.178.242.26
cd /opt
tar xzf /var/backups/v12-final-*.tar.gz
systemctl start agent-pilot-v12-{bot,dashboard}
```

---

## 联系我们

- 戴尚好 (bcefghj@163.com)
- 李洁盈 (JieyingLiii@outlook.com)
- GitHub: https://github.com/bcefghj/Agent-Pilot
