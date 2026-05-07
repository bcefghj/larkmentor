# Agent-Pilot · 飞书 AI 校园挑战赛 复赛提交文档

> 赛道：基于 IM 的办公协同智能助手（公开版）
> 命题：Agent-Pilot · 从 IM 对话到演示稿的一键智能闭环
> 提交日期：2026 年 5 月 7 日

---

## 一、个人信息

### 小组参赛

| 姓名 | 角色 | 项目中负责的工作简述 | 个人基本信息介绍 | 实习信息 |
|------|------|---------------------|-----------------|----------|
| 李洁盈 | 组长 | 产品需求分析与 PRD 撰写；飞书 Bot 交互流程设计（对话 UX、卡片 UI 布局与文案）；Dashboard 界面视觉设计（三段式布局、飞书蓝配色、状态色系）；竞品调研（Coze / Dify / 传统飞书 Bot 对比矩阵）；产品宣传网页设计与文案策划；演示视频脚本策划与录制协调 | （学校/专业/学历/毕业时间待填） | （待填） |
| 戴尚好 | 成员 | Multi-Agent Pipeline 核心架构设计与全部代码实现（6 Agent 协作流水线）；MiniMax M2.7 LLM 深度集成（tool calling、联网搜索、prompt engineering、响应清理）；飞书 Bot 后端开发（lark-oapi WebSocket 长连接、CardKit 交互卡片、Doc API 文档写入）；Dashboard 后端实现（FastAPI + SSE 实时推送）；反向 MCP Server 开发；多端协同框架（Flutter 移动端 + WebSocket SyncHub）；阿里云 ECS 服务器部署运维（systemd + nginx + UFW）；CI/CD 流程搭建（GitHub Actions）；测试体系设计与执行（16 个单元测试 + 竞赛 e2e 真实 API 测试） | （学校/专业/学历/毕业时间待填） | （待填） |

---

## 二、项目结果展示

---

### 1）Demo 展示

#### 在线体验入口（评委可直接点击体验）

| 入口 | URL | 说明 |
|------|-----|------|
| 产品介绍网页 | http://8.136.98.175 | 产品全景介绍 + 比赛完成情况 + 效果对比 + 技术亮点 |
| Live Demo（独立页面） | http://8.136.98.175/demo.html | 全屏对话 UI，左侧 6 个预设场景一键体验，实时展示 Agent 执行过程 |
| Dashboard | http://8.136.98.175/dashboard | 实时 Agent 协作过程可视化（Dify 风格三段式布局） |
| MCP Server | http://8.136.98.175/sse | 反向 MCP，Cursor/Claude Desktop 可直接接入调用 Agent-Pilot 工具 |
| 技术白皮书 PDF | http://8.136.98.175/agent_pilot_report.pdf | 50 页 A4 技术文档，含架构图、代码详解、测试报告 |
| GitHub 仓库 | https://github.com/bcefghj/Agent-Pilot | 完整源码 185 文件，MIT 开源 |

#### Demo 演示流程说明

**演示场景 1：文档生成全链路闭环（场景 A+B+C+F）**

1. 用户在飞书 IM 中发送："帮我写一份 AI Agent 多端协同技术方案"
2. IntentAgent 识别意图 → verdict = "ready", task_type = "doc"
3. 飞书回复启动卡片，显示任务 ID 和 Pipeline 阶段
4. PlannerAgent 生成 7 章结构化大纲，发送确认卡片（Human-in-the-Loop）
5. 用户点击"确认"按钮
6. ResearchAgent 通过 MiniMax tool calling 联网搜索，获取 12 条 2024-2026 年最新数据
7. WriterAgent 按章节撰写，融合搜索数据，生成 5646 字内容
8. ReviewAgent 5 维度评估（数据:4/5 结构:5/5 引用:4/5 密度:4/5 字数:5/5）→ PASS
9. BuilderAgent 调用飞书 Doc API 写入文档，生成分享链接
10. 飞书回复交付卡片：绿色标题 + 任务摘要 + 耗时 92s + 文档链接 + 操作按钮

**演示场景 2：PPT 生成（场景 D）**

1. 用户发送："做一份 8 页关于飞书开放平台集成的 PPT"
2. ppt_pipeline 自动执行：大纲 → 搜索 → 撰写 → 审核 → python-pptx 生成
3. 最终产出 8 页 .pptx 文件（含 Speaker Notes），通过飞书 Drive API 上传
4. 交付卡片含下载链接，耗时 118s

**演示场景 3：模糊意图主动澄清（加分项）**

1. 用户发送："帮我做个汇报"
2. IntentAgent 识别为模糊意图 → verdict = "clarify"
3. 飞书发送澄清卡片，引导用户补充具体内容
4. 用户补充后自动进入对应 Pipeline

**演示场景 4：多端协同（场景 E）**

1. 用户在飞书移动端发起任务
2. 同时打开 Web Dashboard（http://8.136.98.175/dashboard）
3. Dashboard 通过 SSE 实时展示 Agent 工作进度（agent.start / agent.done 事件流）
4. Flutter 移动端同步显示任务状态（WebSocket SyncHub）

---

### 2）核心部分代码展示

#### 核心代码 1：Multi-Agent Pipeline 编排（pilot/agents/pipeline.py）

```python
"""Pipeline 编排 — 6 Agent 协作流水线。
参考 CrewAI 顺序流水线模式 + LangGraph TypedDict 共享状态。"""

MAX_REVIEW_ITERATIONS = 3

async def doc_pipeline(state: AgentState) -> AgentState:
    """文档生成流水线: Planner → Research → Writer ⇄ Review → Builder"""
    event_log = _get_event_log(state)
    start_time = time.time()

    # Phase 1: 大纲规划
    await _emit(event_log, "agent.start", {"agent": "PlannerAgent"})
    planner = PlannerAgent()
    state = await planner.safe_execute(state)
    await _emit(event_log, "agent.done", {"agent": "PlannerAgent",
                "outline_count": len(state.get("outline", []))})

    # Phase 2: 联网搜索
    await _emit(event_log, "agent.start", {"agent": "ResearchAgent"})
    researcher = ResearchAgent()
    state = await researcher.safe_execute(state)
    await _emit(event_log, "agent.done", {"agent": "ResearchAgent",
                "results_count": len(state.get("research_results", []))})

    # Phase 3: 撰写 + 审核循环（最多 3 轮）
    writer = WriterAgent()
    reviewer = ReviewAgent()
    for i in range(MAX_REVIEW_ITERATIONS):
        await _emit(event_log, "agent.start", {"agent": "WriterAgent", "iteration": i+1})
        state = await writer.safe_execute(state)
        await _emit(event_log, "agent.done", {"agent": "WriterAgent"})

        await _emit(event_log, "agent.start", {"agent": "ReviewAgent"})
        state = await reviewer.safe_execute(state)
        if state.get("review_pass"):
            await _emit(event_log, "agent.done", {"agent": "ReviewAgent", "pass": True})
            break
        # 不通过 → feedback 注入 → 重写
        await _emit(event_log, "agent.revise", {"feedback": state["review_feedback"][:100]})
        state["intent"] += f"\n[Review Feedback Round {i+1}]: {state['review_feedback']}"

    # Phase 4: 构建交付
    await _emit(event_log, "agent.start", {"agent": "BuilderAgent"})
    builder = BuilderAgent()
    state = await builder.safe_execute(state)
    await _emit(event_log, "agent.done", {"agent": "BuilderAgent"})

    # Phase 5: 生成任务总结
    state["summary"] = await _generate_summary(state)
    elapsed = round(time.time() - start_time)
    await _emit(event_log, "pipeline_done", {"elapsed_sec": elapsed})
    return state
```

#### 核心代码 2：BaseAgent + 错误恢复（pilot/agents/base.py）

```python
"""Multi-Agent Pipeline 基础设施。
参考 Claude Code 错误恢复决策树 + Harness Engineering 五层架构。"""

class AgentState(TypedDict, total=False):
    """Pipeline 共享状态（参考 LangGraph TypedDict 模式）。
    所有 Agent 通过此 TypedDict 通信，无隐式依赖。"""
    intent: str              # 用户原始意图
    task_type: str           # doc / ppt / trio / chat
    outline: list            # PlannerAgent 输出的结构化大纲
    research_results: list   # ResearchAgent 输出的搜索结果
    draft_sections: list     # WriterAgent 输出的各章节草稿
    review_feedback: str     # ReviewAgent 输出的审核反馈
    review_pass: bool        # 是否通过审核
    artifacts: list          # BuilderAgent 输出的最终产物
    plan_id: str             # 任务 ID（北京时间格式）
    summary: str             # 任务完成总结

class ErrorRecovery:
    """Agent 执行错误的分类与恢复策略。
    参考 Claude Code: prompt_too_long → autocompact; transient → retry."""

    TRANSIENT_ERRORS = (TimeoutError, ConnectionError, OSError)

    @classmethod
    async def retry_with_backoff(cls, fn, max_retries=3):
        for attempt in range(max_retries):
            try:
                return await fn()
            except cls.TRANSIENT_ERRORS:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)  # 指数退避: 1s, 2s, 4s

class BaseAgent(ABC):
    MAX_STEP_BUDGET = 30  # 防止无限循环

    async def safe_execute(self, state: AgentState) -> AgentState:
        """带保护的执行入口。"""
        self._step_count += 1
        if self._step_count > self.MAX_STEP_BUDGET:
            raise StopIteration("步骤预算耗尽")
        try:
            return await ErrorRecovery.retry_with_backoff(
                lambda: self.execute(state))
        except ContextOverflowError:
            state = self._compress_context(state)
            return await self.execute(state)
```

#### 核心代码 3：Circuit Breaker 熔断器（pilot/llm/client.py）

```python
class CircuitBreaker:
    """LLM API 熔断器: CLOSED → OPEN → HALF_OPEN 状态机。
    5 次连续失败 → 熔断 5 分钟 → 半开状态试探恢复。
    参考行业标准 Circuit Breaker Pattern (Martin Fowler)。"""

    FAILURE_THRESHOLD = 5
    RECOVERY_TIMEOUT = 300  # 5 minutes

    def __init__(self):
        self.state = "closed"
        self.failure_count = 0
        self.last_failure_time = 0

    def allow_request(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if time.time() - self.last_failure_time > self.RECOVERY_TIMEOUT:
                self.state = "half_open"
                return True
            return False
        return True  # half_open: 允许一次试探

    def record_success(self):
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.FAILURE_THRESHOLD:
            self.state = "open"
```

#### 核心代码 4：MiniMax Tool Calling 联网搜索（pilot/agents/researcher.py）

```python
class ResearchAgent(BaseAgent):
    """利用 MiniMax M2.7 的 function calling 能力自主搜索。
    不硬编码搜索关键词，模型自主决定搜什么。"""

    _RESEARCH_SYSTEM_PROMPT = """你是专业研究员。
    限制条件：
    1. 只接受 2024-2026 年的数据
    2. 必须使用 web_search 工具获取实时信息
    3. 每个章节至少搜索 2 次
    输出格式: {"data": "研究发现...", "source": "来源URL"}"""

    async def execute(self, state: AgentState) -> AgentState:
        outline = state.get("outline", [])
        results = []
        for chapter in outline:
            # MiniMax 模型自主决定搜索什么
            response = await self._call_llm(
                system=self._RESEARCH_SYSTEM_PROMPT,
                messages=[{"role": "user",
                           "content": f"研究章节: {chapter.get('title', '')}"}],
                tools=[{"name": "web_search",
                        "description": "联网搜索最新信息",
                        "parameters": {"query": {"type": "string"}}}]
            )
            results.append(response)
        state["research_results"] = results
        return state
```

#### 核心代码 5：飞书交互卡片（pilot/surface/feishu/cards/builder.py）

```python
def task_delivered_card(task_id, title, artifacts, summary, elapsed_sec, iterations):
    """任务完成交付卡片。
    设计参考飞书官方 CardKit 最佳实践 + agent-feishu-channel 开源项目。
    绿色标题表示成功，含摘要、耗时、产物链接、操作按钮。"""
    elements = [
        {"tag": "markdown", "content": f"**{title}**\n\n{summary}"},
        {"tag": "markdown", "content": f"⏱ 耗时 {elapsed_sec}s · 迭代 {iterations} 轮"},
    ]
    # 产物链接
    for art in artifacts:
        elements.append({"tag": "markdown",
            "content": f"📄 {art.get('kind','')} [{art.get('title','')}]({art.get('url','')})"})
    # 操作按钮
    elements.append({"tag": "action", "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": "🔄 重新生成"},
         "type": "primary", "value": {"action": "regenerate", "plan_id": task_id}},
        {"tag": "button", "text": {"tag": "plain_text", "content": "📁 归档"},
         "value": {"action": "archive", "plan_id": task_id}},
    ]})
    return {
        "header": {"title": {"tag": "plain_text", "content": "🛬 任务完成"},
                   "template": "green"},
        "elements": elements
    }
```

---

### 3）项目亮点介绍

#### 维度 1：完整性与价值（50%）

**解决什么问题/痛点？**

在快节奏的团队协作中，从一次 IM 对话到最终的演示文稿，传统流程需要经历 5 个阶段、切换 5+ 个应用、耗时 4-8 小时：

1. 意图表达（IM 对话）→ 2. 信息搜集（浏览器搜索）→ 3. 文档撰写（文档编辑器）→ 4. PPT 制作（PPT 软件）→ 5. 归档分享（邮件/云盘）

Agent-Pilot 将整个流程压缩为一句话触发、90 秒自动完成、0 次应用切换。

**AI 在其中起到什么关键作用？**

AI 不是"功能增强"或"辅助工具"，而是**主驾驶（Pilot）**：

- IntentAgent 自动理解用户模糊的自然语言表述，无需固定格式或关键词
- PlannerAgent 自动拆解复杂任务为结构化步骤，生成可执行的大纲
- ResearchAgent 自主决策搜索什么信息（通过 MiniMax tool calling，非规则触发）
- WriterAgent 融合搜索数据按章节撰写，生成高质量长文本
- ReviewAgent 自动评估内容质量并给出修改建议，实现 AI 自我纠错
- BuilderAgent 自动调用飞书 API 将内容写入文档/生成 PPT

人类只在一个关键节点介入：大纲确认（Human-in-the-Loop）。其余 90% 的工作由 AI Agent 自主完成。

**流程是否完整闭环？能否落地使用？**

完整闭环验证（14/14 场景通过，使用真实 MiniMax API）：

| 输入 | Pipeline | 输出 | 耗时 | 状态 |
|------|----------|------|------|------|
| "帮我写份 AI 报告" | doc_pipeline | 飞书文档链接（5646 字） | 92s | PASS |
| "做 8 页 PPT" | ppt_pipeline | .pptx 文件（8 页） | 118s | PASS |
| "三件套" | trio_pipeline | 文档 + PPT + 归档 | 180s | PASS |
| "你好" | chat | 友好回复 + 引导卡片 | <1s | PASS |
| "帮我做个汇报" | clarify | 主动澄清卡片 | <1s | PASS |

已在阿里云 ECS（4核8G，Ubuntu 22.04）上 7×24 稳定运行，通过 systemd 管理进程，nginx 反代，UFW 防火墙保护。

**Demo 是否稳定、可正常演示？**

多重稳定性保障机制：

1. Circuit Breaker 熔断器：MiniMax API 连续 5 次失败后自动熔断，防止级联故障
2. 指数退避重试：瞬时网络错误自动重试（1s → 2s → 4s）
3. 步骤预算：MAX_STEP_BUDGET = 30，防止 Agent 死循环
4. 上下文压缩：Context overflow 时自动截断摘要，不崩溃
5. 持久化 Event Loop：解决 httpx AsyncClient 与 lark-oapi 的事件循环冲突

**带来什么实际价值/效率提升？**

| 任务 | 传统方式耗时 | Agent-Pilot | 提升 |
|------|-------------|-------------|------|
| 研究报告 | 2-4 小时 | 90 秒 | 96% 时间节省 |
| 8 页 PPT | 3-5 小时 | 120 秒 | 97% 时间节省 |
| 应用切换 | 5+ 次 | 0 次 | 100% 消除 |
| 质量审核 | 人工审阅 | AI 5 维度自评 | 系统性保障 |

#### 维度 2：创新性（25%）

**AI 相关创新点**

1. **Multi-Agent Pipeline 架构**（vs 单 Agent）

   不同于 Coze/Dify 等平台的单 Agent + 工具调用模式，Agent-Pilot 采用 6 个专业 Agent 分工协作。每个 Agent 有独立的 system prompt、工具集、验证标准，通过共享 AgentState TypedDict 通信。这种设计的优势：
   - 关注点分离：每个 Agent 只做一件事，做好一件事
   - 可独立测试：单个 Agent 可独立验证
   - 可扩展：添加新 Agent 只需继承 BaseAgent 实现 execute()
   - 质量可控：Review 环节独立把关

2. **LLM 自主 Tool Calling**（vs 规则触发）

   ResearchAgent 不硬编码搜索关键词或使用固定规则触发搜索。而是利用 MiniMax M2.7 的原生 function calling 能力，让模型根据大纲内容自主决定搜什么。搜索行为随 LLM 能力进化自动提升。

3. **Generate-then-Review 自评迭代**（参考 DeepPresenter 论文）

   WriterAgent 与 ReviewAgent 形成闭环。ReviewAgent 从 5 个维度量化评估：数据支撑 / 结构完整 / 引用来源 / 内容密度 / 字数达标。不通过时精确反馈（哪里不好、怎么改），Writer 针对性修改，最多 3 轮。

4. **Human-in-the-Loop 大纲确认**（参考 GenSlide AAAI 2025）

   不是全自动也不是全手动，而是在关键决策点引入人类判断。PlannerAgent 生成大纲后通过飞书 CardKit 发送确认卡片，用户可以一键确认或提出修改。平衡了自动化效率与人类控制力。

5. **Claude Code 架构的错误恢复**

   参考 Anthropic Claude Code 2026 年工程博客，实现：步骤预算防死循环、Circuit Breaker 防级联故障、指数退避应对瞬时错误、上下文压缩防溢出。四重保护确保系统不会因单点故障崩溃。

**方案差异化亮点**

| 对比维度 | Coze（字节） | Dify | 传统飞书 Bot | Agent-Pilot |
|----------|-------------|------|-------------|-------------|
| Agent 模式 | 单 Agent + Plugin | DAG 工作流 | 规则触发 | 6 Agent Pipeline |
| 联网搜索 | 固定插件调用 | 工具节点 | 无 | LLM 自主 tool calling |
| 质量保障 | 无 | 无 | 无 | ReviewAgent 5 维度自评 |
| 人机协同 | 全自动 | 节点确认 | 全手动 | CardKit Human-in-the-Loop |
| 多端同步 | 无 | 无 | 无 | SSE + WebSocket 实时 |
| 错误恢复 | 简单重试 | 节点重试 | 无 | Circuit Breaker + 步骤预算 |
| 可观测性 | 日志 | 节点状态 | 无 | Dashboard Agent 可视化 |

**是否可复用、可推广**

- 架构模式通用：Pipeline 可扩展新 Agent（TranslateAgent、DesignAgent 等）
- LLM 无关：替换 client.py 即可切换 GPT / Claude / 其他模型
- IM 无关：Surface 层抽象设计，可扩展到 Slack、钉钉、微信
- 场景无关：不限于办公，教育/咨询/媒体行业均可复用
- 开源可复制：MIT License，185 文件完整工程代码

#### 维度 3：技术实现性（25%）

**AI 技术使用深度**

| 技术层面 | 具体实现 | 深度说明 |
|----------|----------|----------|
| Prompt Engineering | 6 个 Agent 各自独立 system prompt | 角色定义 + 输出格式约束 + few-shot 示例 + 时间约束 |
| Tool Calling | MiniMax M2.7 原生 function calling | 非规则触发，模型自主决策搜索意图与内容 |
| 多轮迭代 | Writer ⇄ Reviewer 闭环 | feedback 精确注入机制，针对性修改 |
| Context Management | AgentState TypedDict 共享 | 上下文压缩策略（截断历史、摘要化） |
| Error Handling | 四重保护 | Circuit Breaker + 退避 + 预算 + 降级 |
| 响应清理 | _strip_thinking | 移除 MiniMax 内部 `<think>` 和 `[TOOL_CALL]` 标记 |

**技术架构/方案合理性**

四层架构设计（参考 Harness Engineering 五层架构分离思想）：

```
┌────────────────────────────────────────────────────────────┐
│  Surface Layer（展示层）                                      │
│  飞书 Bot (lark-oapi WS) | Dashboard (FastAPI+SSE) | MCP   │
├────────────────────────────────────────────────────────────┤
│  Agent Layer（智能层）                                        │
│  Intent → Planner → Research → Writer ⇄ Review → Builder   │
│  (共享 AgentState TypedDict，Pipeline 编排)                   │
├────────────────────────────────────────────────────────────┤
│  Capability Layer（能力层）                                    │
│  doc_tool · slide_tool · canvas_tool · web_search · lark    │
├────────────────────────────────────────────────────────────┤
│  Infrastructure（基础设施层）                                   │
│  MiniMax Client · Circuit Breaker · EventLog · Session FSM  │
└────────────────────────────────────────────────────────────┘
```

每层职责明确、关注点分离：
- Surface 只负责接收输入和展示结果，不包含业务逻辑
- Agent 只负责任务执行，不关心展示方式
- Capability 只提供原子工具，不关心编排顺序
- Infrastructure 只提供基础能力，不关心上层业务

**工程规范、稳定性、可扩展性**

| 维度 | 实现 |
|------|------|
| 代码规模 | 185 个源文件，Python 90.5% + HTML 5.4% + Dart 3.2% |
| 测试覆盖 | 16 个单元测试文件 + 竞赛 e2e 测试（真实 API，14/14 通过） |
| CI/CD | GitHub Actions（lint + test + deploy 自动化） |
| 进程管理 | systemd 三个 service（bot + dashboard + mcp） |
| 反代/安全 | nginx + UFW（仅开放 22/80/443） |
| 状态管理 | 10 状态 FSM + LEGAL_TRANSITIONS 矩阵 + owner_lock 防冲突 |
| 可观测性 | EventLog + SSE Dashboard + OpenTelemetry 接口 |
| 容错 | Circuit Breaker + 指数退避 + 步骤预算 + 上下文压缩 |

---

### 4）AI 亮点介绍

#### 项目中使用了哪些高阶 AI 技巧？

1. **Multi-Agent 协作编排**：不是一个 LLM 做所有事，而是 6 个专业 Agent 分工协作，每个 Agent 有独立的认知边界和验证标准。参考 CrewAI 角色分工 + LangGraph TypedDict 共享状态。

2. **LLM 自主工具调用（Tool Calling）**：ResearchAgent 不硬编码搜索逻辑，而是让 MiniMax M2.7 通过 function calling 自主决定搜索什么。模型分析大纲内容 → 判断需要什么信息 → 发出 web_search tool_call → 获取结果 → 整理为结构化报告。

3. **生成-评审-迭代循环（Generate-Review-Refine）**：参考 DeepPresenter 论文的 generate-then-review 范式。ReviewAgent 从 5 个维度量化评估生成质量，不通过时精确反馈让 Writer 针对性修改，最多 3 轮确保质量。

4. **Prompt Engineering 最佳实践**：每个 Agent 的 system prompt 精心设计，包含角色定义、输出格式约束（JSON schema）、few-shot 示例、时间约束（"只接受 2024-2026 年数据"）、错误处理指令。

5. **LLM 响应清理**：MiniMax M2.7 响应可能包含内部推理标记（`<think>...</think>`）和工具调用标记（`[TOOL_CALL]...[/TOOL_CALL]`），通过 `_strip_thinking` 正则清理确保输出干净。

6. **Claude Code 错误恢复架构**：参考 Anthropic 2026 年工程博客，实现步骤预算（防死循环）、Circuit Breaker（防级联故障）、上下文压缩（防溢出）。

#### 项目中人和 AI 的分工是怎么样的？

| 环节 | AI 做什么 | 人做什么 |
|------|-----------|----------|
| 意图理解 | IntentAgent 自动分类（doc/ppt/trio/chat/clarify） | 用户只需说一句自然语言 |
| 大纲规划 | PlannerAgent 生成结构化大纲 | 确认或修改大纲（CardKit 卡片） |
| 信息搜集 | ResearchAgent 自主联网搜索 | — |
| 内容撰写 | WriterAgent 按章节生成 | — |
| 质量审核 | ReviewAgent 5 维度自评 | — |
| 产物交付 | BuilderAgent 写入飞书/生成 PPT | 查看结果、精细调整 |

核心理念：**AI 处理 90% 的重复工作，人只在关键决策点介入。**

#### 项目中包含了哪些核心模型选型思路？

| 选型维度 | 决策 | 选型理由 |
|----------|------|----------|
| 基础模型 | MiniMax-M2.7-highspeed | 比赛指定平台；支持 tool calling；highspeed 版本响应快 |
| 搜索方式 | MiniMax 原生联网搜索 | 无需第三方 API 费用；模型自主决策搜索意图；数据时效性好 |
| Agent 框架 | 自研 Pipeline | 轻量无外部依赖；完全可控；适配比赛场景；可独立测试 |
| 文档生成 | 飞书 Doc API | 飞书原生体验；无需跳出 IM；支持富文本 |
| PPT 生成 | python-pptx | 纯 Python；模板可控；无外部服务依赖 |
| 多端同步 | WebSocket + SSE | 低延迟实时推送；浏览器原生支持；无需额外客户端 |

#### 引入 AI 后对原有工作流带来了哪些改变？

**Before（传统工作流）：**
```
IM 讨论需求 → 打开浏览器搜索资料 → 打开文档编辑器逐段撰写
→ 找同事审核 → 修改几轮 → 打开 PPT 软件制作幻灯片
→ 调整排版 → 导出文件 → 分享链接 → 归档
```
- 耗时：4-8 小时
- 应用切换：5+ 次
- 认知负担：高（需要持续集中注意力）

**After（Agent-Pilot）：**
```
在飞书 IM 中说一句话 → 确认大纲 → 等待 90 秒 → 查看结果
```
- 耗时：90-120 秒
- 应用切换：0 次
- 认知负担：极低（只需确认大纲一步）

---

### 5）其他信息补充

#### 真实测试报告（2026-05-07 执行，使用真实 MiniMax API）

| 测试项 | 验证内容 | 结果 | 具体数据 |
|--------|----------|------|----------|
| A-意图（ready） | "帮我写份报告" → ready | PASS | — |
| A-意图（chat） | "你好" → chat | PASS | — |
| B-大纲 | 大纲 >= 5 章 | PASS | 实际 7 章 |
| C-文档字数 | 总字数 >= 1500 | PASS | 实际 5646 字 |
| C-无泄漏 | 无 [TOOL_CALL] 标记残留 | PASS | 已清理 |
| D-PPT 页数 | >= 6 页 | PASS | 实际 8 页 |
| D-PPT 文件 | .pptx 文件生成 | PASS | — |
| E-Dashboard | HTTP 200 可访问 | PASS | — |
| E-V2.0 | 页面含 V2.0 标识 | PASS | — |
| F-绿色标题 | 交付卡片 template=green | PASS | — |
| F-摘要 | 卡片含任务摘要 | PASS | — |
| F-耗时 | 卡片含耗时信息 | PASS | — |
| F-按钮 | 卡片含操作按钮 | PASS | — |
| 加分-澄清 | 模糊意图 → clarify | PASS | — |

**总计：14/14 通过（100%）**

#### 难点与解决方案

| 难点 | 问题描述 | 解决方案 |
|------|----------|----------|
| Event Loop 冲突 | httpx AsyncClient 与 lark-oapi 的 event loop 冲突，导致 "Event loop is closed" | 改用单一持久化 asyncio event loop，所有异步操作提交到共享 loop |
| MiniMax 响应标记泄漏 | LLM 输出含 `<think>` 和 `[TOOL_CALL]` 内部标记 | 实现 `_strip_thinking` 正则清理函数 |
| 内容质量不稳定 | 单次生成质量参差不齐 | ReviewAgent 5 维度自评 + 最多 3 轮迭代 |
| API 不稳定 | MiniMax API 偶尔超时或 5xx | Circuit Breaker + 指数退避重试 |
| Agent 死循环 | 复杂任务可能导致无限执行 | MAX_STEP_BUDGET = 30 步骤预算 |
| 上下文溢出 | 长文档生成可能超出 token 限制 | _compress_context 自动截断摘要 |

#### 学术参考

| 论文/项目 | 年份 | 借鉴内容 |
|-----------|------|----------|
| GenSlide (AAAI 2025) | 2025 | Human-in-the-Loop：大纲确认机制 |
| DeepPresenter | 2024 | Generate-then-Review：自评迭代 |
| CrewAI | 2024 | Agent 角色分工 + Pipeline 编排 |
| LangGraph | 2024 | TypedDict 共享状态 |
| Claude Code (Anthropic) | 2026 | 错误恢复决策树 + 步骤预算 |
| Harness Engineering | 2026 | 五层架构分离 |

---

## 二-2、小组成员各自负责部分信息

---

### 戴尚好 — 全栈 / Agent / 部署

#### 核心负责部分 Demo

**Multi-Agent Pipeline 完整实现演示**：

评委可通过 http://8.136.98.175/demo.html 直接体验完整 Pipeline 执行过程。左侧预设 6 个场景覆盖比赛全部要求，每次对话实时展示各 Agent 工作日志和进度条。

**核心代码贡献**：

- `pilot/agents/` 全部 8 个文件（Pipeline 核心，含 6 Agent + base + pipeline 编排）
- `pilot/llm/client.py`（MiniMax 集成 + Circuit Breaker）
- `pilot/surface/feishu/bot.py`（飞书 Bot WebSocket 长连接）
- `pilot/surface/feishu/cards/builder.py`（CardKit 交互卡片）
- `pilot/surface/dashboard/server.py`（FastAPI + SSE + Web Chat API）
- `scripts/server/install.sh`（一键部署脚本）
- `scripts/test_all_scenarios.py`（PRD 全场景测试）

#### 亮点技术实现

1. 6 Agent Pipeline 架构：从零设计并实现完整的 Multi-Agent 协作系统
2. MiniMax tool calling 深度集成：模型自主决策搜索
3. Circuit Breaker 四重容错：确保 7×24 稳定运行
4. 飞书全生态集成：Bot + Doc API + Drive API + CardKit

---

### 李洁盈 — 产品 / 设计

#### 核心负责部分 Demo

**产品设计与交互体验**：

评委可通过 http://8.136.98.175 查看产品宣传网页设计效果，体验飞书蓝主色 + 浅色 Editorial 风格 + 滚动动画等视觉设计。Dashboard（http://8.136.98.175/dashboard）展示三段式布局和状态色系设计。

**核心设计贡献**：

- 产品定位："Agent 是主驾驶，GUI 是仪表盘"核心理念
- 飞书 Bot 交互流程（自然语言触发 → 进度反馈 → 卡片交付）
- CardKit 卡片 UI 设计（视觉层次、信息密度、操作引导）
- Dashboard 三段式布局设计（Result / Detail / Tracing）
- 产品宣传网页信息架构与文案
- 竞品分析矩阵（Coze / Dify / 传统 Bot）

---

## 三、其他信息（自由发挥区）

### 技术栈全景

| 层级 | 技术选择 | 用途 |
|------|----------|------|
| LLM | MiniMax-M2.7-highspeed | tool calling + 联网搜索 + 内容生成 |
| Agent 框架 | 自研 Multi-Agent Pipeline | 6 Agent 协作编排 |
| 后端 | Python 3.10+ / FastAPI / asyncio | Dashboard API + SSE + WebSocket |
| 飞书集成 | lark-oapi | WebSocket Bot + Doc API + Drive API + CardKit |
| 前端 | HTML/CSS/JS | 产品网页 + Dashboard + Demo |
| 移动端 | Flutter | 跨平台多端协同 |
| 部署 | Ubuntu 22.04 / systemd / nginx / UFW | 生产环境运维 |
| CI/CD | GitHub Actions | 自动化测试与部署 |
| 测试 | pytest + 竞赛 e2e | 16 单元测试 + 真实 API 测试 |

### 相关链接

| 资源 | 链接 |
|------|------|
| GitHub 仓库 | https://github.com/bcefghj/Agent-Pilot |
| 产品介绍 | http://8.136.98.175 |
| Live Demo | http://8.136.98.175/demo.html |
| Dashboard | http://8.136.98.175/dashboard |
| 技术白皮书 | http://8.136.98.175/agent_pilot_report.pdf |
| MCP Server | http://8.136.98.175/sse |

---

*Agent-Pilot V2.0 · 从 IM 对话到演示稿的一键智能闭环*
*2026 飞书 AI 校园挑战赛 · 复赛提交*
*戴尚好 & 李洁盈*
