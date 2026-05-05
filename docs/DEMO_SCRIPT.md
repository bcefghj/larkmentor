# Agent-Pilot v12 · 评委 5 分钟 Demo 脚本

> 一镜到底，无切场。脚本时间精确到秒。

## 立意 30 秒 (00:00 - 00:30)

> **「Agent-Pilot 不是单次任务生成器，而是在公司里陪你长期工作的 AI 同事。」**
>
> 它**记得**你 3 个月前的方案，**懂得**何时该出手，**协作**多个 agent 互相验证，**陪伴**你长期沉淀。
>
> 这是飞书 AI 校园挑战赛课题二「Agent-Pilot · 从 IM 对话到演示稿的一键智能闭环」的现场演示。

## Demo 1 — 群聊自然对话触发全链路 (00:30 - 02:30)

### 场景设定
3 人 IM 群聊讨论产品评审：

```
[张三] 下周校园活动复盘汇报，要给老板看
[李四] 对，我有数据
[王五] 我可以帮忙做 PPT，大概 8 页
```

### 演示要点

**意图识别 (00:30 - 01:00)**

- 无需发送任何 `/pilot` 指令
- Agent 通过三闸门主动识别：规则命中 → LLM 判任务 → 最小信息校验
- 飞书弹出 Card 2.0 任务建议卡：
  - 🎯 任务识别：校园活动复盘汇报
  - 来源：群聊 · 执行人：张三（待确认）
  - 计划预览：补充数据 → 生成大纲 → 生成 PPT → 演讲稿 → 归档
  - 5 按钮：[确认生成] [添加资料] [指派他人] [查看详情] [忽略]
- **话术**：6 级 Memory 已自动注入 system prompt — Enterprise（公司财年）+ User（偏好简洁风格）

**Owner 流转 + 上下文确认 (01:00 - 01:30)**

- 张三点 [指派他人] → 选择李四
- 李四点 [接受] → 卡片更新为「李四执行中」
- 李四点 [添加资料] → 上下文确认卡：已用 11 条 IM + 1 文件，输出 = PPT，受众 = 老板
- 李四点 [✅ 确认生成]

**流式生成 + 多 Agent 协同 (01:30 - 02:30)**

- 飞书 cardkit.v1 流式打字机：评委实时看到生成内容逐步呈现
- 5 推理模式自动选择（因 must_validate=True 升级为 Reflection 模式）
- 5 命名 Agent 协同执行：
  - `@pilot` 编排 DAG
  - `@researcher` 召回历史数据（FlowMemory archival）
  - `@validator` 独立审查（5 Quality Gates）
  - `@citation` 标注 claim source
  - `@mentor` 风格审查
- Web Dashboard `/v12/dashboard` 实时可视化 DAG 执行进度

## Demo 2 — `/pilot` 显式指令一键生成 (02:30 - 03:30)

### 操作
私聊 Bot 发送：

```
/pilot 把本周讨论整理成产品方案 + 评审PPT
```

### 演示要点

- 直接跳过三闸门，立即进入规划
- DAG 可视化：在 `/v12/dag/{plan_id}` 看到任务拆解
- 并行执行：`doc.create` + `slide.generate` 并行分组
- 全程通过 8 层安全栈
- 产出：飞书 Docx + PPT + 分享链接
- **话术**：40-60 秒完成所有产物，3-Tier Prompt Cache 降低 90% 重复 prompt 开销

## Demo 3 — 多端同步 + CRDT 离线合并 (03:30 - 04:30)

### 操作
三端分窗展示：

1. **飞书 IM**：cardkit.v1 流式进度 → 完成卡 + 分享链接
2. **Web Dashboard**：任务状态 PPT_GENERATING → REVIEWING → DELIVERED
3. **Flutter 移动端**：实时同步显示

### 离线合并演示

- 故意断网 5 秒
- 在桌面端编辑 1 处
- 重连 → Yjs CRDT 自动合并 ✓
- **话术**：y-py 实现的真正无冲突同步，非模拟

### 归档

- 点 [📦 归档] → archive.bundle 生成分享链接 + 飞书 Docx 摘要

## 收束 30 秒 (04:30 - 05:00)

### 学习闭环展示

- `/skills` 查看自动生成的 SKILL.md
- 本次任务已沉淀进长期记忆
- 下次类似的「校园活动复盘汇报」第 4 次直接命中 SKILL.md

**收束话术**：
> Agent-Pilot：记得 / 懂得 / 协作 / 学习 / 陪伴 / 安全。
>
> 真实数据：32/32 promptfoo 红队通过 + 560+ pytest 全通过 + 8 层安全栈全链路必经。

---

## 评委 Q&A 速查表（12 题）

| Q | A |
|---|---|
| 这是 ChatGPT 套壳吗？ | 560+ 独立测试 + 32 红队 + 从 v1 到 v12 全栈演化，见 `docs/EVOLUTION.md` |
| 三闸门为什么不会误识别？ | 规则命中 ∧ LLM 判任务 ∧ 最小信息满足 + 60min 冷却 + 同主题合并 + 忽略列表 |
| 6 级 Memory 真的注入了吗？ | `core/flow_memory/` + `tests/test_flow_memory.py` + `tests/test_pilot_memory_inject.py` |
| Owner 怎么避免多人冲突？ | `OwnerLock.acquire_for_action` 在高影响动作前严格校验 |
| 多端同步怎么保证一致性？ | Yjs CRDT + WebSocket 广播 + 离线日志合并对账 |
| 多 Agent 怎么避免污染？ | Sub-agent transcript 隔离（独立 context window） |
| LLM 挂了怎么办？ | 三级 fallback：MiMo → ARK(Doubao) → MiniMax，纯规则 heuristic 兜底 |
| 学习闭环怎么实现？ | `PilotLearner` 监听 task_delivered → 3 次相似自动 SKILL.md → 第 4 次直接命中 |
| 飞书生态用了什么？ | WebSocket 长连接 + IM/Docx/Bitable/Calendar API + CLI 200+ 命令集成 |
| 安全栈有哪 8 层？ | Permission → Injection → Hook → PII → Denylist → RateLimit → Sandbox → Audit |
| 推理模式怎么选择？ | 规则自动判断：短指令→ReAct，中等→CoT，含辩论→Debate，must_validate→Reflection，探索→ToT |
| 如何保证生成质量？ | Builder-Validator 分离 + 5 Quality Gates（Completeness / Consistency / Factuality / Readability / Safety） |

---

## 紧急备用方案

| 问题 | 解决方案 |
|------|---------|
| 飞书 Bot 无响应 | 切换到 Dashboard Demo 模式：`AGENT_PILOT_DEMO_MODE=true` |
| LLM API 超时 | heuristic 规划兜底，展示 DAG 结构不依赖 LLM |
| Flutter 编译失败 | 切 Web Dashboard 多端同步演示 |
| 网络不可用 | 本地 Demo 模式 + 预录视频备用 |
