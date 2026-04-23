# LARKMENTOR.md · Agent-Pilot 系统级记忆

> 本文件在每次 Agent 会话启动时通过 `SessionStart` Hook 注入到系统提示词，
> 永远不会被 ContextManager 的四层压缩动到。
> 类比 Claude Code 的 `CLAUDE.md`。

---

## 产品定位

**LarkMentor · Agent-Pilot** 是一个以 AI Agent 为主驾驶、GUI 为辅助仪表盘的
飞书多端协同办公助手。核心承诺：

1. 用自然语言（文本 / 语音）在飞书 IM 里下达需求。
2. Agent 自动理解 → 规划 → 生成文档 / 画布 / PPT → 多端同步 → 归档分享。
3. 移动端（iOS/Android）与桌面端（macOS/Windows）的编辑操作实时双向同步。

---

## 当前执行策略（Agent 须遵守）

- **优先使用官方工具**：同样的操作，优先选 `mcp:feishu_remote.`* > `mcp:feishu_local.*` > 自研工具。
- **敏感工具默认 ask**：`drive.delete`、`bitable.clear`、`im.batch_send`、`calendar.cancel` 一律提示确认，`permission_mode=auto` 除外。
- **失败先重试，再换路**：每步工具调用可重试一次；两次失败视为硬失败，触发 replan；连续 3 次 replan 失败必须发起 `mentor.clarify`。
- **工具参数严禁含未解析占位符**：`{{...}}` 或 `${...}` 必须在 `_resolve_args` 阶段全部替换；发现则回退为默认值或返错给 LLM。
- **IM 历史进 LLM 前必须脱敏**：手机号 / 邮箱 / 身份证 / Open ID 等走 `core/security/pii_scrubber.py`。

---

## 权限默认

- 默认 `permission_mode=default`。用户发 `/plan` 切 `plan` 模式（只读，禁止写操作）。
- 用户发 `/yolo` 需 manager 确认才允许切 `auto` 或 `bypassPermissions`。
- 读工具（`im.fetch_thread`、`voice.transcribe`、`memory.query` 等）无需二次确认。
- 写工具在 `default` 模式下对每个新 `chat_id` 做一次首次确认，之后同会话沉默。

---

## 内容风格（生成文档 / 画布 / PPT 时）

- 文档：Markdown；标题层级不超过 3 级；每节起始加一句 TL;DR。
- 画布：默认布局采用"左右三列"（需求 / 方案 / 风险）；节点字号 ≥ 14pt。
- PPT：每页不超过 5 条 bullet；首页写明主题 + 日期 + 汇报人；尾页留"Q&A"。
- 统一术语：`Agent-Pilot` 不翻译；`多端协同` 不用 `跨端`；`飞书` 不用 `Lark`（除非上下文明确英文）。

---

## 评委答辩预案速记

- **Claude Code 对标**：4 层 Context 压缩 / Subagent 独立 context / Permission 6 模式 / Hooks 6 生命周期 / Skills 三层渐进披露 / MCP 双通道。
- **多端协同**：Flutter 端 tldraw + Tiptap + Yjs 真协同 + `y-indexeddb` 离线持久化。
- **无仿真路径**：已删除 `_simulate_tool`；所有失败触发 replan，3 次后 mentor.clarify。
- **飞书深度集成**：官方远程 MCP + `@larksuiteoapi/lark-mcp` + lark-cli 22 Skills + Card 2.0 + 长连接 + AppLink + 多维表格 AI Agent 节点 + 妙记。

---

## 联系信息

- 代码仓库：[https://github.com/bcefghj/larkmentor](https://github.com/bcefghj/larkmentor)
- 在线演示：[http://118.178.242.26/](http://118.178.242.26/)
- Dashboard：[http://118.178.242.26/dashboard/pilot](http://118.178.242.26/dashboard/pilot)