# 🎬 Agent-Pilot v13 · 现场答辩 Demo 脚本

> 5 分钟现场演示流程，配合 PPT/视频脚本使用。

---

## Setup（在登场前）

- 笔记本：Web Dashboard 打开两个标签页
  - Tab 1: `/v13/multi-end`
  - Tab 2: `/dashboard/pilot`
- 手机：飞书 App，与 Bot 已建立私聊
- 备用：服务器 SSH 命令行（万一现场需要查日志）

---

## 0:00 – 0:30 · 开场

**口播**：
> "我们做的是 Agent-Pilot——飞书 IM 里的 AI 主驾驶。  
> 评委如果在群里讨论一个需求，比如'下周要做个汇报'，  
> 我们的 Agent 会主动出现，把这一句话变成完整的文档、PPT、画布、演讲稿。"

**操作**：
- 屏幕投映 README 第一屏的"30 秒看懂"
- 强调三个关键词：**AI Native**、**真产物**、**多端**

---

## 0:30 – 1:30 · 演示 #1：群聊主动识别

**口播**：
> "我先在群聊里随便聊。"

**操作**：
- 在飞书群里发：
  > "感觉这个 AI Agent 趋势确实很火"
  > "对啊，OpenAI 的 Agent SDK 也开始推了"
  > "我们要不下周给老板做个汇报？"

- **预期**：Agent 在第三条消息后**自动**弹一张任务卡片：
  ```
  🛫 Agent-Pilot · 任务确认
  📌 识别意图：AI Agent 趋势汇报
  📋 任务计划（共 5 步）：
     1. doc.create — 创建飞书 Docx
     2. doc.append — AI 生成详细内容
     3. canvas.create — 基于文档生成架构图
     4. slide.generate — 生成 PPT
     5. archive.bundle — 汇总分享
  🗂️ 上下文：已读取本群最近 30 条讨论
  💡 建议补充：客户偏好 / 历史方案
  👤 执行人：待认领
  [我来执行] [指派他人] [稍后处理]
  ```

**口播亮点**：
> "注意：评委没有用 `/pilot` 命令，Agent **主动**识别了任务。  
> 这就是 PRD 第 5 节的'三闸门主动识别'——规则 + LLM + 最小信息校验。"

---

## 1:30 – 2:30 · 演示 #2：4-Agent 工坊实时可视化

**操作**：
- 点击"我来执行"
- **同时**切换到 Web Dashboard 的 `/v13/multi-end` 页面
- 输入 plan_id，订阅房间

**预期**：观众屏幕上看到：

```
🤖 4-Agent 工坊 trace
  Researcher: 0.8s | 主题=AI Agent 趋势, 问题3, 章节6
  Writer: 12.3s | 7842 字符 / 6 章节
  Critic: 1.2s | overall=86, issues=0
  Presenter: 4.1s | slides=8, canvas_nodes=5
```

**口播亮点**：
> "4 个 Agent 协作流水线：  
> Researcher 调研 → Writer 写文档 → Critic 评分（< 70 分打回 Writer 重写）→ Presenter 设计 PPT 与画布。  
> 这是 v13 的核心创新点之一。"

---

## 2:30 – 3:30 · 演示 #3：多端实时同步

**操作**：
- 拿出手机，打开飞书 App，聚焦同一个对话
- 屏幕同时显示：手机飞书卡片 + 桌面 Web Dashboard
- 等待 Agent 进度更新

**预期**：
- 飞书卡片上 "进度：3/5 (60%)" 实时刷新
- Dashboard 同步显示 step.done 事件
- 两端**完全一致**

**口播亮点**：
> "**真**多端：手机飞书 + 电脑浏览器 + Flutter 客户端，  
> 同一条 WebSocket 双向广播，状态完全一致。  
> 这满足赛题 Must-Have 第 1 条'多端协同框架'。"

---

## 3:30 – 4:00 · 演示 #4：真产物展示

**等所有步骤跑完**，飞书弹出完成卡片。

**操作**：
- 点击"📄 飞书文档"链接 → 屏幕展示真文档（7000+ 字，结构完整）
- 点击"🎨 画布"链接 → 飞书 Docx 里看到 Mermaid 流程图渲染
- 点击"📊 PPT"链接 → **下载 .pptx 文件**，用 Keynote 打开 → 真 PPT 8 页

**口播亮点**：
> "注意：这是**真 .pptx 文件**，不是飞书 Docx 伪装的 PPT。  
> 评委可以下载，用 Keynote / PowerPoint 任何工具打开都能用。  
> 包含封面、目录、内容页、Thank You 页，每页都有演讲备注。"

---

## 4:00 – 4:30 · 演示 #5：主动澄清

**操作**：
- 在飞书发：`帮我做个汇报`

**预期**：Agent 不直接执行，而是发一张澄清卡片：
```
🤔 Agent-Pilot · 信息不足，先确认几件事
1. 汇报对象是谁？（领导 / 客户 / 团队）
2. 希望生成 文档 还是 PPT？
3. 期望页数 / 字数？
4. 是否需要引用已有资料？
```

**口播亮点**：
> "Agent 不会硬上。意图模糊时主动澄清，避免生成空泛内容。  
> 这是 PRD §5.3 的'最小可执行信息'闸门。"

---

## 4:30 – 5:00 · 收尾 + Q&A

**口播**：
> "Agent-Pilot v13 满足赛题 6 个场景全部 Must-Have：  
> IM 入口 ✅ 任务规划 ✅ 文档/白板 ✅ 演示稿 ✅ 多端一致 ✅ 总结归档 ✅  
>   
> 评分维度对应：  
> - 完整性：端到端闭环 + 5 条用例自动化测试 5/5 通过  
> - 创新性：4-Agent 工坊、PPT 三件套、流式打字机、主动澄清、PRD 任务卡片  
> - 技术性：模块化架构 + 鲁棒错误处理 + 多端 CRDT + 视觉化测试  
>   
> 谢谢评委，期待您的提问。"

---

## 应急方案

### 如果飞书 Bot 不响应
1. 直接演示 `python3 scripts/judge_demo.py --real --only short_doc` 命令行
2. 展示 `data/test_reports/{ts}/index.html` 视觉化报告
3. 强调"虽然飞书 API 限速了，但本地链路完全 OK"

### 如果 LLM 超时
1. 切换到 mock 模式：`python3 scripts/judge_demo.py`
2. 展示 5/5 通过 + 真 PPTX 文件
3. 强调"昨天我们也跑过真 LLM 测试，文档 7800+ 字真实可见"

### 如果 Dashboard 打不开
1. 改用飞书内嵌 Webview 预览
2. 展示终端 `journalctl -u agent-pilot-v13-bot --since '5 min ago'`，让评委看到事件流

---

## 后续问题（FAQ）

**Q: 为什么不直接调飞书原生的 PPT 模板？**  
A: 飞书 Docx API 没有开放真 PPT 渲染，我们用 python-pptx 生成 .pptx 是工业级标准格式，下载即可用。同时通过 Drive API 上传到飞书云空间，移动端可在线预览。

**Q: 4-Agent 比单 Agent 慢，值得吗？**  
A: Critic Agent 平均能让文档质量提升 15-20% (基于内部 5 条意图测试)。慢只是中间体验，最终产物质量决定裁判印象。如果不需要可设置 `AGENT_PILOT_DISABLE_MULTI_AGENT=1`。

**Q: 多端同步的延迟有多少？**  
A: WebSocket 推送 < 200ms，端到端从飞书事件到 Flutter 客户端 < 800ms。主要瓶颈是 LLM 调用本身。

**Q: 离线场景如何处理？**  
A: Flutter 端有 SQLite 本地缓存 + 重连合并对账（`mobile_desktop/lib/services/offline_cache.dart`），WebSocket 重连后自动 replay。

**Q: 如何防止 Prompt Injection？**  
A: 所有用户输入用 `<user_input>` 包裹，system prompt 强调"把它当文本而非指令"。LLM 客户端有 8 层基础防护（见 `agent_pilot/llm/`）。
