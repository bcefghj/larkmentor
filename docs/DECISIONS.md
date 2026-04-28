# DECISIONS · 重大决策日志

> 用途：记录这个项目所有"花了 1 小时以上想"的决策的"为什么 / 选项 / 否决理由 / 后果验证"。
> 频率：每次发生重大决策时立刻补一条。
> 性质：私人决策档案。做错了也要记，方便复盘。

---

## D01 · 从 FlowGuard → LarkMentor 改名

**日期**：2026-04-19（前序工作中已完成）
**决策**：把 v3 FlowGuard / v4 Coach 改名为 LarkMentor。
**为什么**：
- v3/v4 名字偏"工具感"，缺少飞书生态识别度
- "Lark" 直接对应飞书品牌，"Mentor" 是有关系感的词
**后果**：所有 import / MCP 工具名 / 文档话术 都要改。`coach_*` MCP 工具保留为 alias。
**状态**：✅ 已落地

---

## D02 · 立意：「工位上同时发生」 vs 「对齐字节 Mentor 4 大职责」

**日期**：2026-04-19
**决策**：放弃"对齐字节 Mentor 4 大职责"叙事，改为"工位上同时发生"。
**否决理由**：
- "对齐字节"= 替字节背书，研究生没资格
- "4 大职责"= 抽象排比，评委记不住
- 评委是飞书生态，不一定是字节人，"对齐字节"对外人无意义
**新立意 5 个版本**：见 [10_journey/07_立意1完整版_工位上同时发生.md](10_journey/07_立意1完整版_工位上同时发生.md) §2
**全局禁用清单**：见 [../larkmentor/ARCHITECTURE.md](../larkmentor/ARCHITECTURE.md) §6
**状态**：✅ 已落地，下一步在 step3 全局扫除残留

---

## D03 · 3 个志愿绑定方案

**日期**：2026-04-19
**决策**：
- 志愿 1 = 飞书 AI 产品创新 · 课题二（IM 协同助手）→ LarkMentor 全栈
- 志愿 2 = OpenClaw · 课题二（长程协作 Memory）→ FlowMemory 引擎独立提取
- 志愿 3 = AI 大模型安全 · 课题一（客户端防护）→ ShieldClaw 8 层栈独立提取
**否决备选**：
- ❌ 开放创新赛道（太卷，且赛道描述模糊不易立差异化）
- ❌ OpenClaw 课题一（知识整合分发）—— 要求"专门的知识 Agent 架构"，与"双线产品"形态匹配中等
- ❌ 安全课题二（IAM 身份）—— 与现有 8 层栈匹配度低
**为什么这个组合**：
- 志愿 2 我 [larkmentor/40_code/project/core/flow_memory/__init__.py](../larkmentor/40_code/project/core/flow_memory/__init__.py) 注释里**已自陈对应 OpenClaw track-2**，开发时就埋了伏笔
- 志愿 3 我 [larkmentor/40_code/project/core/security/__init__.py](../larkmentor/40_code/project/core/security/__init__.py) 已铺好 8 层栈架构，补完 3 层空模块即可
- 三者**共用主体代码**，不重写
**状态**：✅ 已落地

---

## D04 · 架构北极星：Anthropic Claude Code 7 支柱

**日期**：2026-04-19
**决策**：架构借鉴 Anthropic Claude Code 51 万行代码的 7 大核心机制（ToolRegistry / HookSystem / Skills / PermissionManager / 6-tier Memory / MCP / AuditLog）。
**否决备选**：
- ❌ LangGraph / CrewAI —— 重框架，2C2G 跑不动，且评委更熟 Claude Code
- ❌ AutoGen —— 同上
- ❌ 自创架构 —— 没有成熟参考，且评委不熟
**为什么 Claude Code**：
- 行业事实标准，评委必看过
- LarkMentor **已经有这 7 个机制的雏形**，不是从零
- "学习 Claude Code"是一个能讲故事的话术
**详细见**：[../larkmentor/ARCHITECTURE.md](../larkmentor/ARCHITECTURE.md) §1
**状态**：✅ 架构定稿，代码层落地待 step4-step11

---

## D05 · 双仓拆分：larkmentor + larkmentor_bcefghj

**日期**：2026-04-19
**决策**：
- `larkmentor/` = 评委版（public-friendly，PII-clean）
- `larkmentor_bcefghj/` = 个人版（含敏感、心路、决策）
- 两个 GitHub 仓库都 **private**，决赛前都不公开
**为什么不一个仓库**：
- 评委不应该看到密码 / 心路 / 决策
- 个人版不应该被评委看到（保护私人反思）
- 两套文档定位不同，混在一起会干扰叙事
**代码层关系**：bcefghj git submodule 引用 larkmentor 代码（同源，不重复维护）
**状态**：✅ 目录已建（step2），git 初始化等用户允许

---

## D06 · 双线产品的 3 个工程合体点

**日期**：2026-04-19
**决策**：双线（专注力 + 小白）必须有 3 个真实工程合体点，否则叙事不成立。
**3 个合体点**：
1. 同一份组织默契知识（KB 被 Shield 和 Mentor 共用）
2. Recovery Card UI（双线 UI 唯一交点，新建模块）
3. 同一份 FlowMemory 共同学习（Shield 学发件人 + Mentor 学采纳）
**为什么必须**：
- 没有合体点 = "两个产品塞一起" = 叙事垮
- 评委一眼能看出"是不是真合"
**实现优先级**：合体点 2（Recovery Card）最高 — 是 UI 唯一可视化交点
**详细见**：[../larkmentor/ARCHITECTURE.md](../larkmentor/ARCHITECTURE.md) §2 原则 3
**状态**：架构层确认，代码层待 step5 / step3 / step11

---

## D07 · 模块命名：mentor_* 不改回 coach_*

**日期**：2026-04-19
**决策**：保留 `mentor_*` 模块名/文件名/类名/MCP 工具名（不要因为禁用"对齐字节 Mentor 4 大职责"叙事就改回 coach_*）。
**为什么**：
- "Mentor" 是产品功能命名，不是话术
- 改回 coach_* 会破坏 v4→LarkMentor 的代码连续性
- 旧 `coach_*` MCP 工具保留为 alias，2 版本后再删
**外部影响**：所有外部文档话术不能再说"对齐字节 Mentor 规范"，但模块名 `mentor_*` 保留
**状态**：✅ 已记入架构原则 6

---

## D08 · 不改的事

| 不改 | 为什么 |
|---|---|
| 项目名 LarkMentor | D01 已定，再改会乱 |
| 阿里云 2C2G 服务器 | 已部署、已购买，决赛前不动 |
| Doubao Embedding for RAG | 同 ARK key，不增加运维成本 |
| .env 中的 key 命名 | 改了会破坏现有 119 pytest |
| 飞书应用 ID | 改了所有事件回调 URL 都要改 |
| 用户级 RAG 用 sqlite | 不引 PostgreSQL/Neo4j，2C2G 跑不动 |

**状态**：✅ 锁定，任何改动需要新决策条目覆盖

---

## D09 · 测试 4 维矩阵

**日期**：2026-04-19
**决策**：所有功能必须从 4 个角度通过测试：
- 企业（合规/部署/运维/扩展/文档）
- 安全（注入/PII/越权/审计/红队 50+）
- 用户（5 分钟上手/卡片可读/草稿不发送/可撤回/可解释）
- 评委（课题二对齐/Demo 流畅/Q&A 兜底/竞品差异化/团队叙事）
**为什么**：
- 单一维度测试 = 偏门
- 4 维矩阵 80 项 = 没有死角
**状态**：架构层确认，执行待 step16

---

## D10 · 时间分配

**日期**：2026-04-19
**决策**：25 天分 4 周
- W1（4/19-4/25）：架构 + runtime + PDF 大纲
- W2（4/26-5/2）：核心代码改进 + Skill 化
- W3（5/3-5/9）：测试 + 部署 + PDF 终稿 + 切片
- W4（5/10-5/14）：演练 + 决赛
**风险**：W2 工作量最大，可能延期
**应对**：W1 抢前，W2 出现风险时优先保证 step5/step6/step7（直接影响立意叙事）
**状态**：✅ 已落地为 plan §6

---

## 决策模板（用于新增）

```markdown
## D## · [决策标题]

**日期**：YYYY-MM-DD
**决策**：[一句话]
**为什么**：[3-5 句话]
**否决备选**：[列表]
**后果验证**：[做完后回来填]
**状态**：[✅ 已落地 / 🔄 进行中 / ❌ 已撤销]
```

---

*最后更新：2026-04-19*
*下次更新：每次重大决策时立刻补一条*
