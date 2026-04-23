---
name: larkmentor-shield
description: 消息层守护 · 六维分级信息（P0-P4）+ 免打扰代回复 + 紧急升级。Use when user asks to "最近消息是否有重要的", "帮我挡一下群消息", "整理今天的消息摘要".
when_to_use: 消息筛选 / 优先级分类 / 免打扰 / 紧急升级路由
version: 1.0.0
allowed-tools: [shield.classify, shield.auto_reply, shield.reaction_ack, shield.urgent_app, shield.urgent_sms]
---

# Smart Shield 入口

## 工作流

1. `shield.classify` 对一条或一批消息打分（0-100 紧急度）。
2. 分数 ≥ 80 且发件人在 VIP 白名单 → `shield.urgent_app` 推送到飞书小程序弹窗。
3. 分数 60-79 → `shield.auto_reply` 用模板代回复（带 [LarkMentor代回复] 标签）。
4. 分数 < 60 → 只做 `shield.reaction_ack`（👀 表情确认看过）。

## 不要做

- 不要把判定结果直接发回群里骚扰；只对私聊触发代回复。
- 不要在 P0 场景使用代回复；P0 一定上推紧急通道。
