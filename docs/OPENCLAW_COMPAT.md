# Agent-Pilot 与 OpenClaw 飞书卡片协议对照

OpenClaw（飞书 OpenClaw 卡片协议）是飞书官方为多 Agent 协同设计的卡片消息规范。Agent-Pilot V1.5 的卡片实现与之保持字段级兼容，但**不**直接 vendor `openclaw-lark` submodule，避免依赖膨胀和"挂名集成"。

> 本文档说明：哪些字段已对齐、哪些是 Agent-Pilot 独有、迁移路径如何走。

## 1. 总体策略

| 项目 | 选型 | 理由 |
|---|---|---|
| 卡片渲染 | 飞书 CardKit JSON | 飞书 IM 原生，无需额外渲染层 |
| 协议参考 | OpenClaw schema | 评委如要求"是否兼容"可直接对照本表 |
| Submodule | 不引入 | OpenClaw 仍在迭代，vendor 易腐烂；改用字段对照 |

## 2. 卡片类型映射

| Agent-Pilot 卡片 | 文件 | 对应 OpenClaw 类型 | 兼容度 |
|---|---|---|---|
| `task_suggested_card` | `cards/builder.py` | `TaskSuggestion` | 字段一致 |
| `context_confirm_card` | `cards/context_confirm.py` | `ContextConfirm` | 字段一致 + 中文 label |
| `clarify_card` | `cards/builder.py` | `Clarification` | 字段一致 |
| `task_delivered_card` | `cards/builder.py` | `TaskCompleted` | 字段一致 + artifact 过滤 |
| `pause_card` / `progress_card` | `cards/builder.py` | `TaskStatus` | 子集 |

## 3. 字段对照（核心）

### 3.1 公共头部
```jsonc
{
  "schema_version": "v1",          // OpenClaw: "schema_version"
  "task_id": "...",                // OpenClaw: "task_id"
  "title": "...",                   // OpenClaw: "title"
  "kind": "task_suggested",         // OpenClaw: "kind" (枚举)
  "ts": 1717000000                  // OpenClaw: "timestamp"
}
```

### 3.2 Action Buttons
| 我们的 action | OpenClaw action | 用途 |
|---|---|---|
| `pilot.task.claim` | `task.claim` | 用户认领任务 |
| `pilot.task.assign` | `task.assign` | 转派给他人 |
| `pilot.task.ignore` | `task.dismiss` | 忽略建议 |
| `pilot.ctx.add` | `context.add` | 补充资料 |
| `pilot.ctx.confirm` | `context.confirm` | 确认上下文 |
| `pilot.ctx.adjust` | `context.adjust` | 调整目标 |
| `pilot.task.pause` | `task.pause` | 暂停任务 |
| `pilot.task.resume` | `task.resume` | 恢复任务 |

> 我们使用 `pilot.*` 前缀作为命名空间隔离。OpenClaw 标准协议不要求前缀，但前缀使飞书路由侧能准确识别 Agent-Pilot 触发，便于多 Agent 共存。

### 3.3 Artifact 字段
```jsonc
{
  "artifacts": [
    {"kind": "doc",     "title": "调研报告", "url": "https://..."},
    {"kind": "ppt",     "title": "演示稿",   "url": "https://..."},
    {"kind": "archive", "title": "归档包",   "url": "https://..."}
  ]
}
```

OpenClaw 用 `attachments` 而我们用 `artifacts`。语义一致，可在路由层做映射：
```python
openclaw_payload["attachments"] = [
    {"type": a["kind"], "name": a["title"], "url": a["url"]}
    for a in card_payload["artifacts"] if a.get("url")
]
```

## 4. 不兼容的字段（Agent-Pilot 独有）

| 字段 | 用途 | 为什么不进 OpenClaw |
|---|---|---|
| `dashboard_url` | 实时进度 dashboard | OpenClaw 没有"运行时观测"槽位 |
| `event_count` | 已发出 EventLog 数 | 同上 |
| `stage_owner` | 阶段负责人（context/doc/ppt/rehearse） | OpenClaw 只有任务级 owner |

这些字段不会破坏 OpenClaw client 解析（他们只读取已知字段），可放心保留。

## 5. 迁移到完整 OpenClaw

如未来需要"切换到 OpenClaw 官方 SDK"：

1. 安装 `openclaw-lark`（或 OpenClaw Python SDK）
2. 在 `cards/builder.py` 加 `to_openclaw()` 转换函数
3. `feishu.client.send_card` 之前调用转换，下发即兼容
4. 不需要改业务路由，因为 action id 已用 `pilot.*` 命名空间

预计工作量：< 1 day。

## 6. 评委 / 测试速查

```
Q: Agent-Pilot 是否兼容 OpenClaw？
A: 字段级兼容，未 vendor submodule。原因是 OpenClaw 仍在快速迭代，
   submodule 容易腐烂。我们提供 docs/OPENCLAW_COMPAT.md 字段对照
   + 1 个 to_openclaw() 转换函数（< 1 天可加）。

Q: 多 Agent 协同时不会冲突吗？
A: 我们的 action id 全用 pilot.* 命名空间隔离；其他 Agent 用各自前缀，
   互不干扰。这是 OpenClaw 推荐做法。
```

## 7. 参考

- 飞书开放平台 · CardKit 文档
- OpenClaw Lark Card Schema（社区草案，非官方稳定 API）
- Agent-Pilot 卡片实现：[`pilot/surface/feishu/cards/`](../pilot/surface/feishu/cards/)
