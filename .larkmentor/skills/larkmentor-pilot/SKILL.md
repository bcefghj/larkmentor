---
name: larkmentor-pilot
description: LarkMentor Agent-Pilot 六场景编排技能包。Use when user asks to "生成文档/方案", "做一张架构图/画布", "出一份PPT/汇报稿", "把群聊整理成", "/pilot".
when_to_use: 用户意图包含 doc/canvas/slide 生成或 "一键方案/架构/汇报" 时触发
version: 2.0.0
allowed-tools: [im.fetch_thread, doc.create, doc.append, canvas.create, canvas.add_shape, slide.generate, slide.rehearse, archive.bundle, mentor.clarify, mentor.summarize]
---

# Agent-Pilot 主技能

当用户意图涉及"从一次 IM 对话到正式演示稿"的全链路时，按下列执行轮廓生成 DAG。

## 执行模板

1. 若意图涉及群聊历史 → `im.fetch_thread(chat_id, limit=50)` 拿上下文。
2. 若意图含"文档/方案/需求" → `doc.create(title)` + `doc.append(doc_token, markdown)`。
3. 若意图含"画布/架构图/流程图" → `canvas.create(title)` + `canvas.add_shape(...)`（多次）。
4. 若意图含"PPT/演示/汇报" → `slide.generate(title, outline)` + `slide.rehearse(slide_id)`。
5. 最后一步一律 `archive.bundle`，把上面产物汇总成一条飞书分享消息。

## 禁忌

- 不要为图方便把 `slide.rehearse` 放在 `slide.generate` 之前。
- 不要在 `doc.append` 的 `markdown` 里直接粘未脱敏的 IM 原文。
- 不要把 outline 写成字符串列表；必须是 `[{title, bullets[]}]` 结构。

## 输出示例

```
{
  "steps": [
    {"step_id": "s1", "tool": "im.fetch_thread", "args": {"limit": 30}},
    {"step_id": "s2", "tool": "doc.create", "args": {"title": "本周评审方案"}, "depends_on": ["s1"]},
    {"step_id": "s3", "tool": "slide.generate",
      "args": {"title": "本周评审演示", "outline": [
        {"title": "背景", "bullets": ["痛点", "目标"]},
        {"title": "方案", "bullets": ["核心思路", "关键模块"]}
      ]},
      "depends_on": ["s1"], "parallel_group": "artifact"},
    {"step_id": "s4", "tool": "archive.bundle", "depends_on": ["s2", "s3"]}
  ]
}
```
