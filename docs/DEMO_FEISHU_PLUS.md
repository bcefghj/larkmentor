# 一句话串联飞书全家桶 Demo（P4.4）

## 口令
```
/pilot 把本周项目群讨论汇总成《Q2 评审方案》文档，做一份 12 页 PPT，生成对比表格和架构图；
在下周二下午 2 点安排评审会议并邀请产品经理；把最终成果归档到 Wiki 「产品/2026Q2」；
把录音交由妙记转写并引用；在 Drive 里建对应附件文件夹。
```

## 预期串联（8 个子应用）

| # | 子应用 | 触发工具 | 产出 |
|--:|--------|---------|------|
| 1 | **IM** | `im.fetch_thread` | 本周群聊 48 条消息 → PII 脱敏 → 进 planner |
| 2 | **妙记 Minutes** | `minutes_fetch` | 最近 1 条逐字稿 + speaker + timestamp |
| 3 | **Docx** | `doc.create` / `doc.append` | 《Q2 评审方案》飞书文档，10 段 + 1 表格 |
| 4 | **多维表格 Bitable** | AI Agent 节点 → Webhook 回写 | 决策行：意图 + 状态 + 分享链接 |
| 5 | **PPT Slide** | `slide.generate` | 12 页 Slidev → PDF → 飞书附件 |
| 6 | **自由画布 Board** | `canvas.create` + `canvas.add_shape` | 架构图（5 节点 + 2 箭头），同步到飞书 Board |
| 7 | **Calendar** | `lark-remote MCP: calendar.event.create` | 下周二 14:00 评审，自动邀请产品经理 |
| 8 | **Drive + Wiki** | `drive.upload_all` + `wiki.node.create` | Drive 附件夹 + Wiki 归档节点 |

## 演示要点
1. IM 单聊 / 群聊均可触发；支持语音长按录音（Flutter 端）。
2. Dashboard 打开 `/pilot/<plan_id>` 看到每一步的 real-time 状态、产物链接、耗时。
3. Flutter 画布端同时打开，架构图 push 进来可即时展示。
4. 产出汇总卡片（Card 2.0，element_id 可局部更新）包含全部 8 个链接。

## 触发脚本（用于 CI / 自动回归）
```bash
curl -X POST http://118.178.242.26/api/pilot/launch \
  -H 'Content-Type: application/json' \
  -d '{"intent":"把本周项目群讨论汇总成《Q2 评审方案》文档...（如上）","open_id":"ou_demo"}'
```
