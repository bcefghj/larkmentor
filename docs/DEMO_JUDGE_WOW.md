# 评委震撼点 Cheatsheet（P4.5）

围绕 Claude Code harness 的六大工程能力，这是当评委提出"再演示点什么"
时你可以随口打出的 6 张王炸。每张都是 10 秒以内可展示、不依赖外网。

## 1. `/context` — 看见 Agent 的大脑
> 「LarkMentor，把你现在的 context 给我看一眼」

IM 输入 `/context` → 返回：
- 当前挂载工具数（含 MCP 导入的远程工具）
- 三层 Skills 清单（22 lark-cli + 3 自研）
- 权限模式（default / plan / dontAsk / bypassPermissions）
- 最近 Hook 调用次数与事件流水

## 2. `/plan <意图>` — Plan Mode 只规划不执行
> 「我想看看 Agent 自己怎么拆 5 个步骤」

IM 输入 `/plan 整理本周群聊做评审 PPT` → 返回 10 步详细计划，但一步都不执行；
等用户口头确认 → 再发 `/pilot …` 真正执行。对应 Claude Code 的 Plan Mode。

## 3. `/skills` — 三层渐进披露
> 「你说挂了 22 个官方 Skills，能证明吗？」

IM 输入 `/skills` → 弹 Card 2.0 清单卡片，按 `source` 分组：
- **larkmentor**（自研 3 个）
- **larksuite-cli**（官方 22 个）
- **third-party**（MCP 导入）

## 4. Subagent 并行分析
> 「整理本周 3 个群聊里的决议」

主 Agent 识别为多目标任务 → 一次性 spawn 3 个 Subagent（每个独立 context 窗口）→
并行跑完 → 只回传摘要。Dashboard 左侧实时显示三路进度条。

## 5. 多维表格 AI Agent 节点
> 「在多维表格里改一行，Agent 能不能自己触发？」

预先在多维表格 AI Agent 节点绑定 `/api/pilot/bitable` webhook。演示：
- 改「需求」一列的值
- 0.3s 内「AI 结果」列从空 → `处理中`
- 15s 后 → `已完成` 并出现分享链接

## 6. Mem0g 跨会话记忆
> 「你昨天跟我说的那个『客户 A 不喜欢深色 UI』，今天你还记得吗？」

演示流程：
1. 会话 A（昨天）：`客户 A 的评审 PPT 请避免深色主题`
2. 重启 Bot（清 session）
3. 会话 B（今天）：`给客户 A 做一份 Q2 评审 PPT`
4. Agent 产出前，调用 `MemoryLayer.recall("客户 A 偏好")` → 自动避深色

## 加料：Autocompact 现场触发
> 「长会话怎么不爆？」

用 `curl` 连发 20 条长文本（每条 3k token）到一个 session，
再发 `/context` → 看到 `layer = L4 autocompact`，token 使用率从 95% 跌到 20%，
最近 5 个文件 + pending tasks + user intent 仍保留。对应 Claude Code 第四层压缩。

## 备用答辩话术
- **Q**：和市面上其他 Agent Framework 有啥不一样？
- **A**：我们做了 Claude Code 51 万行 harness 工程的 80% 最小可用子集——
  4 层 Context 压缩、Subagent 独立 context、6 模式 Permission（deny-first）、
  6 生命周期 Hooks、3 层 Skills 渐进披露、双通道 MCP，
  并与飞书生态深度集成（官方 MCP + lark-cli + Card 2.0 + 长连接 + AppLink + Bitable AI 节点）。
