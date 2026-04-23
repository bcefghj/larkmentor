# LarkMentor v2 · Agent-Pilot Demo 录屏脚本（≤ 5 分钟）

> 目标：**清晰展示多端协同 + Agent 驱动主流程 + Office 套件覆盖**（赛题 3 大验收点）。

---

## 前置准备

1. 启动服务端：`ssh root@118.178.242.26 'systemctl status larkmentor-v2 larkmentor-v2-dashboard larkmentor-v2-mcp'` 确认 3 个服务都 `active (running)`。
2. 在 macOS 上打开 Flutter 桌面端：`cd mobile_desktop && flutter run -d macos`。
3. 手机打开 Android/iOS 版（APK / TestFlight）或备用浏览器。
4. Chrome 打开 `http://118.178.242.26/dashboard/pilot` 作为评委观看入口。
5. 飞书 PC 端登录主账号，打开与 `@LarkMentor` Bot 的私聊 / 测试群。

确保**四块屏幕同时可见**（录屏软件分屏布局）：
- 左上：飞书 PC 端（IM 入口）
- 右上：Chrome Dashboard（观察员视角）
- 左下：Flutter macOS（Co-pilot 驾驶舱）
- 右下：iPhone/Android（移动端同步 + 语音）

---

## 脚本

### 段 1（0:00 - 0:45）| 问题陈述 + 产品定位

**配音**：
> LarkMentor v2 · Agent-Pilot 解决的问题是：**把一次 IM 讨论，自动变成文档 + 画布 + PPT 三端同步的完整成果**。传统做法要开 5 个应用、切 20 次页面；我们让一句自然语言就完成。

**屏幕动作**：
- 全屏展示架构图（[README.md](../README.md) 中的 6 场景图）
- 切换到 4 分屏视图

---

### 段 2（0:45 - 2:15）| 从 IM 触发 Agent

**配音**：
> 第一步，在飞书群里 @ LarkMentor，下达一条自然语言指令。

**飞书 PC 端**输入：
```
/pilot 把今天关于 Agent-Pilot 架构的讨论整理成产品方案和评审 PPT，并画一张架构图
```

**观察点**：
1. Bot 立刻回复 `🛫 Agent-Pilot 已启动 plan_xxx（共 8 步）`，附 Dashboard 链接。
2. **Chrome Dashboard** 的 Plan 列表出现新 Plan，右侧事件流开始刷新。
3. **Flutter macOS** 的 Pilot Home 页自动跳转到新 Plan 并开始显示步骤进度条。
4. **移动端** Pilot Home 页也同步显示同一 Plan。

> 关键话术：**这就是「多端协同」—— 一端触发，四端同步，我没有在任何一端做第二次操作。**

---

### 段 3（2:15 - 3:30）| Agent 驱动主流程

**配音**：
> Agent 现在把意图拆成了 DAG：先拉群聊上下文 → 并行创建飞书文档 / tldraw 画布 / Slidev PPT → 最后 Scenario F 归档生成分享链接。整个过程由 Planner 自主完成，我们不再干预。

**屏幕动作**：
- 在 Dashboard 展开 DAG 图（scenario tag 标注每步属于 A-F 哪个场景）
- 聚焦到 `doc.create` 步骤完成 → 点击飞书 Docx 链接，展示自动生成的文档（有「背景/目标/摘要/下一步」结构）
- 切换到 `canvas.create` → Flutter 桌面端的「画布协作」页面已渲染出架构图（3 节点 + 2 箭头）
- `slide.generate` 完成 → Flutter 桌面端的「演示稿」页面能翻页，底部显示演讲稿

---

### 段 4（3:30 - 4:20）| 移动端语音 + 跨端同步

**配音**：
> 现在演示**语音驱动 + 跨端一致性**：我在手机上长按录音说「第 3 页加一个 2026 Q2 里程碑」，桌面端 PPT 实时更新。

**手机动作**：
- 进入 Voice Input 页 → 长按圆形按钮 → 说："第 3 页加一个 2026 Q2 里程碑"
- 松开 → 弹窗显示转写结果（离线 demo 下为占位文本）→ 确认
- 后端 Orchestrator 收到新指令，生成子 Plan 修改 slide outline

**桌面端/Web 端**：
- Dashboard Pilot 事件流出现新事件
- Slide 页第 3 页自动加入 "2026 Q2 里程碑" bullet

---

### 段 5（4:20 - 4:50）| 离线合并 + 归档

**配音**：
> 最后演示**离线支持**：我把 macOS 断网，仍然能编辑画布；重联后所有改动通过 Yjs CRDT **无冲突合并**。

**屏幕动作**：
- macOS 关 WiFi → 在 Flutter 画布上添加一个 "2026 Q3" 便签
- 开 WiFi → 几秒后 Web Dashboard 画布页也出现便签（无冲突）
- 点击 `archive.bundle` 步骤 → 跳转到分享页 `http://118.178.242.26/pilot/<plan_id>`

---

### 段 6（4:50 - 5:00）| 结尾

**配音**：
> LarkMentor v2：AI Agent 主驾驶，GUI 四端协作，飞书 + Doc + 画布 + PPT 一键闭环。GitHub：`bcefghj/larkmentor`。谢谢。

---

## 备用演示指令（若主流程卡壳）

| 指令 | 预期产物 |
| --- | --- |
| `/pilot 帮我画一张 Agent-Pilot 的架构图` | canvas 场景单独演示 |
| `/pilot 为飞书 AI 比赛写一份评审 PPT` | slide 场景单独演示 |
| `/pilot 帮我处理` | 演示 Advanced Agent 主动澄清 |
| `我的飞行员` | 列出历史 Plan |

## 评分对齐自检表

| 赛题验收要点 | 本次 Demo 对应段落 |
| --- | --- |
| 多端协同（移动 ↔ 桌面 实时双向同步） | 段 2、段 4 |
| Agent 驱动主流程（IM → 多场景编排） | 段 2、段 3 |
| Office 套件覆盖（IM + Doc + PPT/Canvas） | 段 3（三工具并行）、段 5（归档） |
| 自然语言交互（文本 + 语音） | 段 2（文本）、段 4（语音） |
| 加分：离线支持 | 段 5 |
| 加分：Advanced Agent（澄清/总结/推荐） | 段 3（澄清 fallback）+ 备用指令 |
| 加分：富媒体画布 | 段 5（便签）+ 段 3（节点/箭头） |
| 加分：飞书 API 深度集成 | 整个段 3（Docx API） |
