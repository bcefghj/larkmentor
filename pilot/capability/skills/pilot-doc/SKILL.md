---
name: pilot-doc
version: 1.0.0
description: |
  当用户需要"写文档/写方案/写报告/写需求/写复盘"时调用。
  覆盖飞书 Docx 创建、内容生成、批写入；支持图片、表格、Mermaid 等富媒体。
  富媒体能力是 PRD §G3 加分项。
metadata:
  requires:
    tools: [doc.create, doc.append]
  read_only: false
  requires_approval: false
---

# pilot-doc

> Agent-Pilot 的文档生成 Skill（PRD §F-08）。

## 1. 何时使用

以下场景应使用本 Skill：

- 用户明确要"写文档/写方案/写报告/写需求/写复盘/做个总结"
- 用户给出了 `/docx/<token>` 链接希望追加内容
- Plan 中有 `doc.create` 或 `doc.append` 工具节点

不应使用本 Skill：

- 用户只想生成 PPT/画布（用 pilot-slide / pilot-canvas）
- 用户要"分析数据" → 用 lark-base 的 data-query

## 2. 调用流程

```
1. doc.create(title)       → 返回 doc_token + url
2. doc.append(doc_token)   → markdown 留空，工具会调 LLM 生成 + 批写入
```

## 3. 富媒体（PRD §G3 加分项）

doc.append 生成的 markdown 会包含：

- **图片**：`![alt](url)` → 工具自动上传到飞书 Drive 并替换为飞书图片 token
- **表格**：标准 markdown 表格 → 转飞书 table block
- **Mermaid**：```mermaid 代码块 → 飞书 Docx 自动渲染流程图
- **代码**：```lang 代码块 → 飞书 code block

## 4. 与其他 Skill 的协作

- `pilot-canvas`：从本 Skill 产出的 markdown 中提炼架构图
- `pilot-slide`：从本 Skill 产出的 markdown 中提炼 PPT 大纲
- `lark-doc`（lark-cli 官方）：raw 操作时使用，本 Skill 是高层封装
