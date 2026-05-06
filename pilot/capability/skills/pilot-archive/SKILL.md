---
name: pilot-archive
version: 1.0.0
description: |
  当任务完成、需要交付/汇总/归档时调用。
  汇总 doc + canvas + slide 等产物，生成 markdown 摘要 + 分享链接。
metadata:
  requires:
    tools: [archive.bundle]
  read_only: false
---

# pilot-archive

> Agent-Pilot 的归档交付 Skill（PRD §F-13）。

## 1. 何时使用

- Plan 的最后一步（强制约定）
- 用户明确要"分享/导出/归档/打包"

## 2. 调用流程

```
archive.bundle(title?) → 自动从 step_results 收集所有产物
返回: share_url + summary_md + items[]
```

## 3. 摘要内容

- 任务标题 + 时间
- 所有产物链接（doc / canvas / slide）
- 可在飞书任务中心 / Web Dashboard 查看
