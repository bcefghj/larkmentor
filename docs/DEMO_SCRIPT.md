# Agent-Pilot V1 · 答辩演讲稿（5 分钟版本）

> 给戴尚好 / 李洁盈 答辩用。中括号是动作提示。

---

## 开场（30 秒）

> 「各位评委好。我们做的是 Agent-Pilot V1——飞书 IM 中的 AI 主驾驶 Harness。
> 一句话能力：把"群聊讨论 → 文档 → 画布 → PPT + 演讲稿"压成 90 秒一键交付。」

[切到主页 http://8.136.98.175/，展示动画 + 5 层架构]

> 「我们重写了整个项目，旧的 v3 / v4 / v12 / v13 全部废弃，因为我们意识到：
> **2018 风格的工具 + DAG 架构已经过时了**。
> 2026 年的 AI Agent 工程，差异化在 Harness——也就是包在 LLM 外的那一切。」

---

## Demo 1 · 模糊意图触发主动澄清（45 秒）

[在飞书 Bot 里发：「帮我做个汇报」]

> 「v13 此处会做出一个错误的假设——直接生成。
> V1 触发**三闸门意图识别**——规则层 → LLM → 最小信息——如果信息不足，**主动弹澄清卡**。」

[弹出橙色澄清卡。点「文档 + PPT 三件套」]

> 「v13 的 P0 BUG 是这 4 个按钮全部失效——服务器日志显示 'Unknown card action: clarify_answer'。
> V1 把所有 clarify 按钮统一到 `pilot.clarify.*` 命名空间，**单一 router 处理**，并用单元测试守护。」

---

## Demo 2 · 三件套（90 秒）

[发：「产品方案 + 架构图 + 评审 PPT 三件套」]

> 「这条命令会触发 V1 的核心创新——**三 Agent GAN Harness**。
> 这个设计借鉴了 Anthropic 2026-03 最新发表的论文 'Harness Design for Long-running Apps'。」

[切到 Dashboard 实时面板]

> 「左边是会话列表，**中间是 Agent thinking 流**——每一个 LLM 调用、每一次工具执行、每一次权限决策都实时显示。
> 右边是 8 步 Claude Code Harness Loop 的高亮进度——这是我们直接借鉴 Claude Code 内部的 query() 循环结构。」

[等到产物生成完，点开链接]

> 「真 .pptx 文件——可以用 Keynote 或 PowerPoint 打开。
> 5 个语义化模板：Hero / TwoColumn / Cards / List / Quote——这套设计哲学融合了 Gamma 的 card-based 思路和 Beautiful.ai 的设计规则约束。」

---

## Demo 3 · 多端协同（45 秒）

[左屏开飞书手机端，右屏开 http://8.136.98.175/multi-end]

> 「多端用 pycrdt-websocket——一个 Yjs 兼容的 Python CRDT 实现。
> 任何一端的状态变化，**全部三端**——飞书 / Web Dashboard / Flutter 客户端——实时同步。」

[Flutter 客户端如果有，再开一个]

> 「**离线支持是 CRDT 天然能力**——网络断开 30 秒后再连，自动 reconcile，不丢内容。
> 这是 PRD 加分项 G1，对我们来说零成本。」

---

## Demo 4 · MCP 反向暴露（30 秒）

> 「我们最特别的创新——V1 把自己暴露成 MCP server。
> 也就是说：**Cursor / Claude / Trae 反过来调 V1 的工具**。」

[在 Cursor 中配置 MCP server: http://8.136.98.175/mcp/]

[Cursor 调用 doc.create]

> 「评委用您熟悉的 IDE，就能直接调 V1 的飞书工具——这就把整个 V1 变成了一个**对外开放的 Agent 工具集**，可以集成进任何 AI 工作流。」

---

## 创新点与评分（45 秒）

> 「我们 V1 的创新性不在做了多少功能，而在**架构选型的工程素养**：

> **1. 5 层 Harness 架构**——Runtime / Context / Capability / Governance / Surface，借鉴 Modern Agent Harness Blueprint 2026

> **2. 8 步 Claude Code harness loop**——直接复刻 Claude Code 内部 query() 循环

> **3. 三 Agent GAN harness**——Anthropic 2026-03 最新长任务方法论

> **4. Cognition 单线程写约束**——Researcher/Critic 只读、Writer 独占

> **5. 飞书官方生态深度集成**：lark-oapi WS + CardKit 2.0 streaming + lark-cli 29 SKILL submodule + lark-mcp 反向暴露

> 这些都不是我们闭门造车想出来的——**全部都是行业头部团队 2025-2026 年公开的最佳实践**——而我们做的工程价值是把它们**串联起来真正落地到一个 IM Agent 上**。」

---

## 结尾（15 秒）

> 「v13 的三件套要 6 分钟，V1 是 90 秒。这不是性能优化的胜利，这是架构选型的胜利。
> 75 条测试守护、AGENTS.md cascade、PRD 100% 覆盖证明，全部公开在 [github.com/bcefghj/Agent-Pilot](https://github.com/bcefghj/Agent-Pilot) 的 v1-rewrite 分支。
> 谢谢！」

---

## 备用问答

**Q: 为什么不用 LangGraph？**
> 「我们想要的状态机非常具体——8 步 Claude Code loop。LangGraph 是更通用的工具，对我们的场景反而是过度抽象。但我们的 Runtime 层用 Protocol 定义了边界，可以平滑迁移到 LangGraph。」

**Q: 三 Agent harness 会不会成本翻倍？**
> 「会的，所以我们设了 1 轮重试上限（max_retries_per_sprint=1）。代价是约 2x token，回报是质量门控（任一维度 < 60 分自动重试）。这个权衡来自 Anthropic 论文——他们在 4 小时长任务上证明 20x 成本能换 5x+ 质量。」

**Q: 如果飞书 token 失效呢？**
> 「所有工具都有本地 fallback——doc.create 写到 artifact:// 文件、slide.generate 写出 .pptx 到 /artifacts。即使飞书全挂，V1 仍能在本地完成端到端任务。」

**Q: 修复了哪些 v13 的问题？**
> 「最关键的：澄清卡按钮 P0 BUG（clarify_answer 失效），我们用 pilot.clarify.* 命名空间统一并加测试守护。次要的：缓存命中率从 0 到 80%+、token 浪费从 7000 字塞 history 到 30 字 artifact handle、权限从无到 4 级。」
