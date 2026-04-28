# LarkMentor · Agent-Pilot v3 · 10 分钟 Demo 视频逐帧台本

目标观众：评委（飞书 AI 校园挑战赛，Agent-Pilot 赛道）。
录制分辨率：1920×1080，屏幕分屏布局见每段说明。
建议时长：10:00（含 20 秒片头 + 40 秒片尾），场景 A–F 各 1:30，加分项 1:30。

---

## 0:00 – 0:20 · 片头（20s）

- **画面**：黑底 fade-in，居中 logo + 标题「LarkMentor · Agent-Pilot · 从 IM 对话到演示稿的一键智能闭环」。
- **旁白**（可字幕）：
  > 这是 LarkMentor v3，一个对标 Claude Code 工程架构、深度接入飞书 2026 官方栈、Flutter 四端真协同的 Agent-Pilot。接下来十分钟，您会看到全部 6 个必做场景 + 4 个加分项，没有仿真，没有剪辑跳步。

---

## 0:20 – 1:50 · 场景 A · IM 意图入口（1:30）

- **布局**：左半屏飞书桌面客户端，右半屏 Flutter 移动端模拟器（或真机投屏）。
- **操作序列**：
  1. 飞书私聊 `LarkMentor Bot` 输入 `/help`，展示完整指令帮助卡（Card 2.0，元素可折叠）。
  2. 发送：`/pilot 把本周"新人培训"群的讨论整理成产品方案 + 架构图 + 评审PPT`。
  3. 立即切到 Flutter 移动端，按住底部麦克风按钮语音说："同时帮我预订周四下午 3 点的评审会议"。
  4. Flutter 端本地 `record` 录音 → multipart 上传 → 后端 Doubao ASR 转写 → 自动补发到同一 Plan 的 `/pilot` 入口。
- **口播重点**：Card 2.0 的 `element_id` 精准 patch、多端入口共用一个 `plan_id`。

---

## 1:50 – 3:20 · 场景 B · 任务理解与规划（1:30）

- **布局**：全屏 Dashboard Pilot 驾驶舱（`/dashboard/pilot/{plan_id}`）。
- **操作序列**：
  1. 打开驾驶舱，展示 LangGraph 六节点状态机（gather / plan / dispatch / verify / reflect / replan）实时进度。
  2. 展示 `/context` 指令结果：当前 token 使用、四层压缩触发线（40/60/78/92%）、已执行 hook 事件流。
  3. 故意触发一次 `drive.delete`（敏感工具），展示 Permission Gate deny-first 弹出 `AskUserQuestion` 卡片。
  4. 在卡片上点"允许本次"，plan 继续；另开一个 `/plan`（Plan Mode）展示"只规划不执行"模式下非 readonly 工具被 block。
- **口播重点**：这是 Claude Code harness 的最小可用子集，评委看到的不是单纯 LLM 调用，而是带 verify / replan / permission / hook 的完整 agent loop。

---

## 3:20 – 4:50 · 场景 C · 文档 + 白板真协同（1:30）

- **布局**：左半屏 Flutter 桌面端，右半屏 Flutter 移动端。
- **操作序列**：
  1. 两端同时打开 Plan 生成的文档（Tiptap + Yjs）和画布（tldraw + Yjs）。
  2. 桌面端输入一段需求描述；移动端几乎同时看到字符流入（y-websocket awareness 光标可见）。
  3. 移动端在画布插入一个圆形 + sticky note；桌面端同步出现。
  4. 在 Plan 驾驶舱点击「插入架构图」，Agent 自动在画布里铺出 4 层方框 + 箭头（`/pilot 富媒体` 能力）。
- **口播重点**：这不是"三个客户端看同一份 HTTP"，而是 CRDT 真协同，光标/选区/presence 全部可视化。

---

## 4:50 – 6:20 · 场景 D · 演示稿生成与排练（1:30）

- **布局**：全屏浏览器（生成的 Slidev PPT）。
- **操作序列**：
  1. 驾驶舱点击「生成 PPT」，Agent 根据文档 + 白板抽取要点 → Slidev Markdown → 静态 HTML。
  2. 打开生成的 PPT，展示首页 + 架构图页 + 结尾页。
  3. 在驾驶舱点「一键排练」，调用 Agent 的 `rehearse` 子工具：给每一页生成讲稿（带语气标记）。
  4. 展示讲稿卡片回流到飞书 IM 原对话（Card 2.0 折叠容器展开）。
- **口播重点**：PPT 不是截图，是可交互 HTML；讲稿是真实 LLM 生成，带 timeout/retry/token budget/prompt 防注入加固。

---

## 6:20 – 7:50 · 场景 E · 多端一致性与离线合并（1:30）

- **布局**：左半屏桌面 Flutter，右半屏移动 Flutter。
- **操作序列**：
  1. 两端同时在 Tiptap 文档里敲字，确认实时同步；
  2. **移动端开启飞行模式**，继续编辑 5 行文字 + 一张图片；
  3. **桌面端**同时编辑同一段落；
  4. **移动端关闭飞行模式**：2 秒内 y-indexeddb flush → y-websocket resync，两端自动无冲突合并；
  5. 展示 `awareness` 光标重新出现在两端。
- **口播重点**：CRDT 天然合并、y-indexeddb 离线持久化、hive 双层缓存；这是加分项 1 的完整兑现。

---

## 7:50 – 9:20 · 场景 F · 飞书全家桶串联交付（1:30）

- **布局**：四分屏：飞书 IM / 飞书文档 / 多维表格 / 飞书日历。
- **操作序列**（详见 `docs/DEMO_FEISHU_PLUS.md`）：
  1. 一句话 `/pilot 启动项目Kickoff`：
  2. **IM**：自动发确认卡到群（Card 2.0 + AppLink 回跳）；
  3. **Doc**：自动建立会议纪要；
  4. **Bitable AI Agent 节点**：改一行状态 → 回写 AI 字段；
  5. **Calendar**：创建评审会议 + 邀请成员；
  6. **Minutes**：会议中自动拉妙记逐字稿（带 speaker + timestamp）；
  7. **Board**：生成看板；
  8. **Drive**：归档 PPT 附件；
  9. **Wiki**：沉淀到知识库。
- **口播重点**：同时跑 8 个子应用，MCP 远程 + 本地 + CLI Skills 三源协同。

---

## 9:20 – 9:40 · 加分项集中展示（20s）

- **画面切换**：
  - `/skills` 列表：22 官方 + 3 自研 Skills
  - `/mcp` 列表：remote + local + 自研 3 个 MCP 源
  - `/context` 触发 autocompact 的实时进度条
  - Mem0g 跨会话记忆：上周的决议被本周 Plan 自动引用

---

## 9:40 – 10:00 · 片尾（20s）

- **画面**：项目首页 + 技术报告 PDF 封面 + GitHub 仓库 URL。
- **字幕**：
  > LarkMentor · Agent-Pilot · 飞书 AI 校园挑战赛 · 2026 年 4 月
  > 源码：[https://github.com/bcefghj/larkmentor](https://github.com/bcefghj/larkmentor) ｜ 在线体验：[http://118.178.242.26/](http://118.178.242.26/)

---

## 录制前 Checklist

- 服务器 `/health` 200
- 飞书 Bot 已发布最新版本，WS 长连接已跑起来
- Flutter 桌面/移动端都拉最新 `main` 分支并构建（`scripts/build_flutter_all.sh`）
- Dashboard 已清理旧 Plan（`scripts/demo_offline.sh`）
- 录屏软件关闭通知、关闭 VPN、关闭截图水印
- OBS 场景预设：左右分屏 / 四分屏 / 单屏三套