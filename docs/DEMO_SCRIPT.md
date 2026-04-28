# Agent-Pilot v7 · 评委 5 分钟 Demo 脚本

> 一镜到底，无切场。脚本时间精确到秒。

## 立意 30 秒 (00:00 - 00:30)

> **「Agent-Pilot 不是单次任务生成器，而是在公司里陪你长期工作的 AI 同事。」**
>
> 它**记得**你 3 个月前的方案，**懂得**何时该出手，**协作**多个 agent 互相验证，**陪伴**你长期沉淀。
>
> 这是飞书 AI 校园挑战赛课题二「Agent-Pilot · 从 IM 对话到演示稿的一键智能闭环」三线产品的现场演示。

## 群聊讨论模拟 30 秒 (00:30 - 01:00)

3 人 IM 群聊：

```
[u1: 张三] 下周校园活动复盘汇报，要给老板看
[u2: 李四] 对，我有数据
[u3: 王五] 我可以帮忙做 PPT，大概 8 页
```

一句语音输入：「最好用季度数据」（飞书 STT 自动转文字）。

**说明话术**：
- 我没有发任何 `/pilot` 指令；
- Agent 完全靠 IM 对话三闸门主动识别（PRD §5）。

## 主动识别 + 任务卡片 30 秒 (01:00 - 01:30)

飞书弹出 Card 2.0 任务建议卡：

- **🎯 任务识别**：校园活动复盘汇报
- **来源**：群聊 g_xxx · **执行人**：张三（待确认）
- **任务计划**：补充数据 → 生成大纲 → 生成 PPT → 演讲稿 → 归档分享
- **上下文状态**：📦 已识别 11 条消息 · 💡 建议补充：历史复盘 / 预算表
- **5 按钮**：[确认生成] [添加资料] [指派他人] [查看详情] [忽略]

**说明话术**：
- 这是 PRD §5.4 完整任务卡片
- 6 级 Memory 已自动注入：Enterprise（我司财年）+ Workspace（运营组模板）+ Group（"活动 = 校园推广"）+ User（喜欢简洁风格）
- 三闸门：规则命中 ∧ LLM 判任务 ∧ 最小信息满足 → READY

## Owner 流转 + 上下文确认 30 秒 (01:30 - 02:00)

张三点 [指派他人] → 群成员选择器卡 → 选择「李四」

李四点 [接受任务] → 任务卡更新为「由李四执行中」

李四点 [添加资料] → 弹出上下文确认卡：
- 已用：IM 11 条 + 1 个上传文件
- 缺失：无 — 信息已满足 ✓
- 输出：PPT · 受众 = 老板 · 启用 Citation

李四点 [✅ 确认生成]。

**说明话术**：
- PRD §6 owner 锁定：现在李四是 owner，其他人不能重复触发
- PRD §7.4 ContextPack 标准契约：7 字段全填（task_goal / source_messages / source_docs / user_added_materials / output_requirements / constraints / owner）

## 多 Agent 协同生成 90 秒 (02:00 - 03:30)

打开 Web Dashboard `/v7/pilot`：

实时可视化 5 named agents 协同（多窗口分屏）：
- `@pilot` 编排 → 拆 DAG（5 推理模式 = CoT，因为 must_validate=True 升级为 Reflection）
- `@researcher` 召回 3 个月前的复盘文档（FlowMemory archival）
- 工具执行：`doc.create` → `slide.generate` → cardkit.v1 流式打字机更新进度卡
- `@validator` 独立审查（5 Quality Gates：Completeness 90 / Consistency 88 / Factuality 85 / Readability 92 / Safety 100）
- `@citation` 标 12 个 claim source（数据来自飞书 Bitable + Wiki）
- `@mentor` 风格审查（3 条修订要点，针对老板汇报场景）
- `@shield` 安全审查（PII 脱敏 + 注入检测，pass）

**说明话术**：
- Builder-Validator 严格分离 → 永不自审（Sub-agent transcript 隔离）
- 5 Quality Gates 真实评分（不是 mock）
- 全程通过 8 层安全栈（不绕过）
- 这是 README 里 5 推理模式 + 4 multi-agent 的真实落地

## 多端同步 + 归档 60 秒 (03:30 - 04:30)

三端实时同步（屏幕分窗）：
1. 飞书 IM Card：cardkit.v1 流式打字机 100% → 完成卡 + 分享链接
2. Web Dashboard：任务详情页 state 从 PPT_GENERATING → REVIEWING → DELIVERED
3. Flutter 移动端（Q3 加分项）：同时显示完成

故意断网 5 秒 → 在桌面端编辑 1 处 → 重连 → y-websocket CRDT 自动合并 ✓（PRD §15 加分项 1 离线支持）

李四点 [📦 归档] → archive.bundle 生成最终分享链接 + 飞书 Docx 摘要

## 长期沉淀回看 30 秒 (04:30 - 05:00)

切到 `/v7/triad` 三线协同雷达：
- 🛡️ Shield：本周已拦截 142 条低优先级消息
- ✍️ Mentor：本周生成 27 个草稿
- 🛫 Pilot：本月完成 8 个任务，**自动生成 3 个 SKILL.md**

切到 `/v7/memory` 6 级 Memory 时间线：
- Enterprise / Workspace / Department / Group / User / Session 各级 markdown 内容

**收束话术**：
> 这次任务沉淀进我的长期记忆。下次类似的「校园活动复盘汇报」，第 4 次直接命中 SKILL.md，跳过 60% 规划阶段。
>
> 这就是 Agent-Pilot 三线产品的「记得 / 懂得 / 协作 / 学习 / 陪伴 / 安全」六个关键词。
>
> 真实数据：32/32 promptfoo 红队通过 + 75 次真实 LLM A/B 矩阵（见 `tests/reports/ab_matrix.json`）+ 169 个 PRD 单元测试。

---

## 评委可能问的 12 题（兜底答案）

详见 [docs/ARCHITECTURE_v6.md §8](ARCHITECTURE_v6.md) + 以下 v7 新增：

| Q | A |
|---|---|
| 你这是 ChatGPT 套壳吗？ | 169 PRD 单元 + 32 promptfoo + 75 A/B + 3700 行新代码（v3-v7 全栈），看 `docs/PRD_IMPLEMENTATION.md` |
| 三线产品不会精神分裂吗？ | 3 个工程合体点：KB / Recovery Card 升级版 / FlowMemory；见 `docs/EVOLUTION.md` |
| 6 级 Memory 真的注入了吗？ | 看 `core/agent_pilot/application/memory_inject.py` + `tests/test_pilot_memory_inject.py` 7 个测试 |
| Pilot 主流程怎么避免误识别？ | 三闸门：规则命中 ∧ LLM 判任务 ∧ 最小信息满足 + 60min 冷却 + 同主题合并 + 忽略列表 |
| Owner 怎么避免多人冲突？ | `OwnerLock.acquire_for_action` 在高影响动作前严格校验 |
| 多端同步怎么保证一致性？ | y-websocket CRDT + 离线编辑无冲突合并 |
| 多 agent 怎么避免互相污染？ | Sub-agent transcript 隔离（独立 context window） |
| Citation Agent 是 Anthropic 独家吗？ | 不是。参考 Anthropic Citations API 设计，开源公开技术 |
| Promptfoo 32/32 是真的吗？ | `tests/promptfoo/reports/redteam_v7.md` 真实测试报告（每条带 LLM judge reason） |
| A/B 矩阵 75 次是真的吗？ | `tests/reports/ab_matrix.json` 真实 LLM 调用，无 mock |
| 如果 MiniMax 挂了怎么办？ | `agent/providers.py` 自动 fallback Doubao |
| 学习闭环怎么实现？ | `PilotLearner` 监听 task_delivered → 3 次相似自动 SKILL.md 第 4 次直接命中 |
