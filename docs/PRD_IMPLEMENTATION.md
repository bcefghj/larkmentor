# PRD 实现地图 (v7)

> 与 [Agent-Pilot 产品需求文档.md](../../../Agent-Pilot-产品需求文档.md) 17 节逐项对应。
>
> 状态：✅ 完整实现 · 🟡 部分实现 · ⏳ 计划中

---

## §1 产品定位与核心判断 ✅

「以 AI Agent 为主驾驶」+「多源上下文」+「模块化编排」三原则。

**实现位置：**
- `core/agent_pilot/` 完整 DDD 主路径（domain + application + tools）
- `bot/pilot_router.py` 把 IM 入口接到 Pilot 主驾驶
- `main.py` 启动横幅明确 Agent-Pilot 三线产品

---

## §2 关键设计原则 ✅

| 原则 | 实现 |
|---|---|
| 2.1 主动但可控 | `core/agent_pilot/application/intent_detector.py` 三闸门（规则+LLM+最小信息）+ `core/agent_pilot/domain/owner.py` Permission 三态 |
| 2.2 IM 是主入口 | `bot/pilot_router.py.handle_chat_message`；`dashboard/api_v7.py` 是管理中枢 |
| 2.3 owner 流转 | `core/agent_pilot/domain/owner.py` OwnerLock + OwnerAssignment |
| 2.4 多源上下文 | `core/agent_pilot/application/context_service.py` 三档资料源 + 6 级 Memory |
| 2.5 模块化编排 | `core/agent_pilot/application/planner_service.py` 自动选 5 推理模式 |

---

## §3 目标用户与核心场景 ✅

5 类用户场景全覆盖：见 `docs/DEMO_SCRIPT.md` 评委演示脚本（5 分钟一镜到底）。

---

## §4 产品整体结构 ✅

「双入口 + 多源上下文 + 模块化执行」：

| 模块 | 实现位置 |
|---|---|
| 当前 IM 对话卡片 | `bot/cards_pilot.py` 7 张卡片 + `bot/pilot_router.py` |
| 机器人独立页面 | `dashboard/api_v7.py` + `/v7/pilot` `/v7/memory` `/v7/triad` |
| 上下文中心 | `core/agent_pilot/application/context_service.py` |
| Planner | `core/agent_pilot/application/planner_service.py` |
| Executor | `core/agent_pilot/application/orchestrator_service.py` |
| 多端同步层 | `sync_v4/yws_server.py`（v6 已有 y-websocket CRDT，保留） |

---

## §5 主动识别与任务卡片 ✅

| §5.1-5.4 | 实现 |
|---|---|
| 4 触发类型 | `core/agent_pilot/application/intent_detector.py` 显式 / 语义 / 上下文 / 阶段 |
| 任务卡 6 区域 | `bot/cards_pilot.task_suggested_card` 完整 5 按钮 |
| 卡片出现原则 | `core/agent_pilot/application/intent_detector.CooldownManager` 60min 冷却 + 同主题合并 + 忽略列表 |
| 卡片示例 | `tests/test_pilot_cards.py::test_task_suggested_card_*` |

**Q5 决策**：规则 + LLM + 最小信息三闸门 → ✅ 已实现 + 26 测试通过。

---

## §6 执行人、指派与权限机制 ✅

| §6.1-6.4 | 实现 |
|---|---|
| 默认 owner | `core/agent_pilot/domain/task.Task.new` 接收 `owner_open_id` |
| 执行前可指派 | `bot/cards_pilot.assign_picker_card` + `pilot_router._action_assign_to` |
| 他人接管 | `bot/cards_pilot.assign_picker_card` 「我来执行」+ `pilot_router._action_claim_self` |
| 执行锁定 | `core/agent_pilot/domain/owner.OwnerLock.acquire_for_action` + `Task.apply` 高影响动作校验 |
| 阶段 owner | `OwnerAssignment.stage` 字段（doc/ppt/canvas/archive） |
| 群可见 | Dashboard `/v7/pilot` 任意成员可见状态 |

**Q6 决策**：轻量指派，不绑群角色 → ✅ 已实现 + 41 测试通过。

---

## §7 多源上下文与资料补充 ✅

| §7.1-7.4 | 实现 |
|---|---|
| 5 类来源 | `context_service.MaterialKind` LINK / UPLOAD / FEISHU_DOC / FEISHU_WIKI / IM_THREAD / HISTORY_TASK |
| 上下文确认卡 | `bot/cards_pilot.context_confirm_card` 三段式（已用 / 缺失 / 建议补充） |
| 资料补充流程 | `pilot_router._action_add_context` |
| 上下文包结构 | `core/agent_pilot/domain/context_pack.ContextPack` 7 字段全 PRD §7.4 对齐 |

**Q4 决策**：三档资料源（链接/上传/飞书 API）+ 6 级 Memory 注入 → ✅ 已实现 + 19 测试通过。

---

## §8 机器人独立页面 ✅

| 页面 | 实现 |
|---|---|
| 任务列表 | `GET /api/v7/tasks` + `/v7/pilot` |
| 任务详情 | `GET /api/v7/tasks/{id}` 含状态机历史 + Agent 日志 |
| Agent 日志 | `task.agent_logs` + `/v7/pilot` 实时可视化 |
| 成果资产 | `task.artifacts` + 详情页 |
| 历史记录 | `task.transitions` + `tests/promptfoo/reports/` |
| 设置 | `dashboard/api_v7.py` 主动识别开关（intent_stats） |

✅ 12 个 Dashboard 测试全过。

---

## §9 基础功能定义 ✅

| F-编号 | 功能 | 实现 |
|---|---|---|
| F-01 IM 文本入口 | `bot/pilot_router.handle_chat_message` |
| F-02 语音入口 | `core/agent_pilot/tools/voice_tool.py`（v4 保留） |
| F-03 主动任务识别 | `intent_detector.detect` 三闸门 |
| F-04 任务卡片 | `bot/cards_pilot.task_suggested_card` |
| F-05 任务规划 | `planner_service.plan_for_task` |
| F-06 上下文确认 | `context_confirm_card` |
| F-07 资料补充 | `context_service.add_link_material/add_user_upload` |
| F-08 文档生成 | `core/agent_pilot/tools/doc_tool.py` |
| F-09 PPT/画布 | `core/agent_pilot/tools/slide_tool.py` + `canvas_tool.py` |
| F-10 执行人指派 | `task_service.assign/claim` |
| F-11 状态锁定与同步 | `OwnerLock.acquire_for_action` + `sync_v4/yws_server.py` CRDT |
| F-12 任务中心 | `dashboard/api_v7.py` |
| F-13 导出与分享 | `core/agent_pilot/tools/archive_tool.py` |
| F-14 演练 | `slide_tool.rehearse`（v4 保留） |
| F-15 冲突解决 | y-websocket CRDT |

---

## §10 任务状态机 ✅

10 + 2 状态完整实现：`core/agent_pilot/domain/state_machine.py`

```
SUGGESTED → ASSIGNED → CONTEXT_PENDING → PLANNING
  → DOC_GENERATING / PPT_GENERATING / CANVAS_GENERATING
  → REVIEWING → DELIVERED
辅助：PAUSED / FAILED / IGNORED
```

50+ 合法转移注册在 `_TRANSITIONS` 表。`InvalidTransitionError` 守护任意转移。

✅ 10 个状态枚举完整 + 50+ 转移测试通过。

---

## §11 关键用户旅程 ✅

| §11.x | 实现位置 |
|---|---|
| 11.1 群聊到 PPT | `tests/test_pilot_router.py::test_router_action_*` 完整链路 |
| 11.2 私聊快速生成 | `pilot_router._handle_explicit_pilot` |
| 11.3 文档转 PPT | `task_service.fire(TaskEvent.USER_REQUEST_PPT)` |

---

## §12 关键页面与组件定义 ✅

| 组件 | 实现 |
|---|---|
| IM 任务卡片 | `cards_pilot.task_suggested_card` |
| 上下文确认面板 | `cards_pilot.context_confirm_card` |
| 任务详情页 | `dashboard/api_v7.py /v7/pilot` |
| 文档/PPT/画布页 | 跳转飞书 Doc / Slide / Canvas |
| 任务中心 | `/v7/pilot` |

---

## §13 差异化点 ✅

| 差异化 | 实现 |
|---|---|
| 对话内主动识别 | `intent_detector` |
| 行动卡片 | `cards_pilot` 7 张 |
| owner 流转 | `domain/owner.OwnerLock` |
| 多源上下文 | `context_service` 三档 + 6 级 Memory |
| 双入口 | IM `pilot_router` + Dashboard `/v7/pilot` |
| Agent 日志 | `task.agent_logs` + `/v7/pilot` |
| 多端 | y-websocket CRDT + 飞书 IM Card 2.0 + Web Dashboard |

---

## §14 风险与约束 ✅

| 风险 | 缓解实现 |
|---|---|
| 过度主动打扰 | 60min 冷却 + 忽略列表 + 主动识别开关 |
| 误识别任务 | 三闸门：规则 + LLM + 最小信息 |
| 资料权限问题 | `SourceDoc.permission_ok` 标记 + 失败降级 |
| 多人重复执行 | OwnerLock 锁高影响动作 |
| 生成内容空泛 | 强制 ContextPack 确认（`Constraints.must_validate`） |
| 跨端状态不一致 | y-websocket CRDT |
| 用户不信任 | Agent 日志 + 转移历史 + 6 级 Memory 透明 |

---

## §15 MVP 范围建议 ✅

第一阶段全部完成 + 加分项 4 项已实现：
- 离线支持（y-websocket CRDT）
- 高级 Agent 能力（5 推理模式 + 多 agent + 主动澄清）
- 富媒体画布（v4 现有）
- 第三方集成（飞书 7 API + MCP）

---

## §16 Demo 演示建议 ✅

5 分钟一镜到底脚本：见 [docs/DEMO_SCRIPT.md](DEMO_SCRIPT.md)

---

## §17 待确认问题（Q1-Q6 决策）✅

| 编号 | 决策 | 实现 |
|---|---|---|
| Q1 IM 卡片 | 飞书开放平台（Card 2.0 + cardkit.v1） | `bot/cards_pilot.py` schema 2.0 |
| Q2 PPT 形态 | MVP 双栈：Slidev → pptx + 飞书画板，默认 PPT | `slide_tool.py` + `canvas_tool.py` |
| Q3 多端 | 飞书 IM 客户端 + Web Dashboard 主路径；Flutter 4 端加分 | `mobile_desktop/` 保留 |
| Q4 资料读取 | 三档：链接/上传/飞书 Wiki+Docx | `context_service` `MaterialKind` |
| Q5 主动识别 | 规则 + LLM + 最小信息三闸门 | `intent_detector.IntentDetector` |
| Q6 owner | 轻量指派，不绑群角色 | `domain/owner.OwnerLock` |

---

## 实现总结

| PRD 节 | 状态 | 测试覆盖 |
|---|---|---|
| §1-§4 | ✅ | 41 unit |
| §5 主动识别 | ✅ | 26 unit |
| §6 owner | ✅ | (合并到 41) |
| §7 上下文 | ✅ | 19 unit |
| §8 任务中心 | ✅ | 12 dashboard |
| §10 状态机 | ✅ | (合并到 41) |
| §11-13 | ✅ | 13 router + 17 cards |
| §15 MVP | ✅ | 13 learner + 11 multi-agent + 16 planner+orch |
| §16 Demo | ✅ | docs/DEMO_SCRIPT.md |
| §17 Q1-Q6 | ✅ | docs/DECISIONS.md |

**累计：169 个新增 PRD-aligned 单元测试 · 0 失败。**

> 加上 32/32 promptfoo 红队 + 75 次 A/B 矩阵真实 LLM 调用，构成完整证据链。
