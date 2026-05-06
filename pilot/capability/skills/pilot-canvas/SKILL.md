---
name: pilot-canvas
version: 1.0.0
description: |
  当用户需要"画架构图/流程图/思维导图/白板/画布"时调用。
  覆盖 tldraw JSON + Mermaid + 飞书白板三种输出形态。
metadata:
  requires:
    tools: [canvas.create, canvas.add_shape]
  read_only: false
---

# pilot-canvas

> Agent-Pilot 的画布生成 Skill（PRD §F-09 部分）。

## 1. 何时使用

- 用户明确要"画架构图/流程图/思维导图/白板/画布"
- 三件套场景中需要画布
- 已有方案文档需要可视化

## 2. 调用流程

```
1. canvas.create(title) → 自动从上游 doc.append 提炼架构
   返回: canvas_id + tldraw_url + mermaid_url + mermaid 代码
2. (可选) canvas.add_shape(canvas_id, ...) → 微调
```

## 3. 三种输出

- **tldraw JSON**：前端 Web Dashboard / Flutter 可加载交互
- **Mermaid 代码**：嵌入飞书 Docx 自动渲染
- **飞书白板**（可选）：当配置了飞书 App 时尝试创建

## 4. 设计原则

- 不超过 12 个节点（保持可读）
- 中文标签
- 默认 LR（Left-to-Right）布局
- 关键路径用粗箭头
