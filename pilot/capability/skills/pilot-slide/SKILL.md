---
name: pilot-slide
version: 1.0.0
description: |
  当用户需要"做 PPT / 演示稿 / 汇报 / slide"时调用。
  生成真 .pptx + Slidev HTML + 演讲稿 markdown，借鉴 Gamma/Beautiful.ai 模板。
metadata:
  requires:
    tools: [slide.generate, slide.rehearse]
  read_only: false
---

# pilot-slide

> Agent-Pilot 的演示稿生成 Skill（PRD §F-09 + §F-14）。

## 1. 何时使用

- 用户明确要"做 PPT / 演示稿 / 汇报 / 幻灯"
- 三件套场景中需要 PPT
- 已有方案文档需要转 PPT

## 2. 调用流程

```
1. slide.generate(title, pages?) → 真 .pptx + Slidev md + 演讲稿
   返回: slide_id + pptx_url + slidev_md_url + speaker_notes_md_url
2. slide.rehearse(slide_id) → 排练版演讲稿（含停顿/重音提示）
```

## 3. 5 种语义化模板（借鉴 Gamma + Beautiful.ai）

| 模板 | 何时使用 | 字数上限 |
|---|---|---|
| Hero | 封面 / 章节首页 | 标题 1 行 + 副标题 2 行 |
| TwoColumn | 左右对比 / 优劣 | 每列 4 条 |
| Cards | 3-4 张并列卡片 | 每卡片 1 句话 |
| List | 数字列表 | 5 条以内 |
| Quote | 引言 / 用户原声 | 1 段 50 字以内 |

## 4. 设计规则（Beautiful.ai 思路）

- 字数超限自动分页
- 标题字体一律 32pt，正文 20-22pt
- 主色 #0F4C81（深蓝）
- 中文优先 PingFang SC，英文 Inter

## 5. 演讲稿（PRD §F-14）

每页 80-150 字 speaker notes，分三段：
1. 开场过渡（10 秒）
2. 要点讲解（30-60 秒）
3. 衔接下页（5 秒）
