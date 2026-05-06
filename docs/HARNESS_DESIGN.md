# Agent-Pilot V1 · Harness Engineering 设计专题

> 本文档是 V1 的"创新点"专题，专为评委 25% 创新分准备。

---

## 1. 什么是 Harness Engineering

Harness Engineering 不是某个具体工具，而是 **2026 年 AI Agent 工程的事实标准范式**：

- LLM 是"控制平面"（reasoning + planning）
- Harness 是包在 LLM 外的一切：state / context / tools / approvals / observability
- 差异化在 Harness（不是 LLM）

来源：Anthropic / Cognition / LangGraph / Kimi CLI 等头部团队 2025-2026 的实践共识。

---

## 2. V1 的 Harness 五大组件

### 2.1 Harness Loop（核心）

V1 不重新发明轮子，**严格按 Claude Code 的 8 步 query loop 复制**：

```python
# pilot/runtime/harness.py::HarnessLoop.run()
async for event in harness.run(session, task, user_message="..."):
    # Step 1: assemble  → system prompt + AGENTS.md cascade + EventLog
    # Step 2: call_llm  → LLMClient.chat(streaming async generator)
    # Step 3: parse     → text blocks + tool_use blocks
    # Step 4: permit    → PermissionGate (deny→allow→classifier→ask)
    # Step 5: execute   → read 并行 / write 串行（Cognition 教训）
    # Step 6: feedback  → tool_result → EventLog
    # Step 7: ctx_check → 超长则 compact / reset
    # Step 8: terminate → 无 tool_use 即结束
```

每一步都可被 `on_event` 订阅，**Surface 层（飞书卡片 / Dashboard / Flutter）**实时显示。

### 2.2 Cache Stability（缓存稳定）

```
system_prompt = (
    CORE_PROLOGUE                    # 全局静态（可全用户共享缓存）
    + AGENTS.md cascade              # 项目级静态（per-repo 缓存）
    + SYSTEM_PROMPT_DYNAMIC_BOUNDARY # 边界 marker
    + Session Info                   # 动态（每次都不同）
)
```

Anthropic prompt cache 命中前缀 → V1 单次 token 成本降 50%+。

### 2.3 Filesystem as Working Memory

大段内容不塞 conversation：

```python
# 不要这样（v13 的做法）
event_log.append("doc_generated", {"markdown": "###" + "..." * 7000})  # ❌ 7K tokens 塞 history

# V1 的做法
art = filesystem_memory.store_text(markdown, kind="docs")
event_log.append("doc_generated", {"artifact_ref": art.uri})  # ✓ 仅 30 字 handle
# 后续 LLM 需要时再 mem.resolve(uri) 拉
```

### 2.4 Permission Gate（4 级）

```
工具调用 → check()
   1. deny rules     → 命中即拒绝（os.* / subprocess.* / rm /etc 等）
   2. allow rules    → 命中即放行（pilot.* / lark-cli.* 白名单）
   3. classifier     → 启发式（含 delete/rm-rf 等关键词）
   4. ask user       → 走 governance.approval 弹卡片二次确认
```

**关键设计**：destructive 工具即使在 allow 列表里，也会强制走 ask（`require_approval_for_destructive=True`）。

### 2.5 Audit Log（append-only）

`data/audit/<yyyy-mm-dd>/audit.jsonl`：

```json
{"ts": 1730000000.5, "kind": "tool_call", "session_id": "sess_x",
 "tool": "doc.create", "verdict": "allow", "duration_ms": 1820}
{"ts": 1730000001.2, "kind": "permission_check",
 "tool": "rm.run", "verdict": "deny", "reason": "禁止删除系统目录"}
```

每条都不可修改，便于 replay / debug / compliance。

---

## 3. 三 Agent GAN Harness（处理长任务）

借鉴 Anthropic 2026-03 最新论文 [Harness Design for Long-running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)：

```
   PlannerAgent (1-4 句 → 16 项 spec)
          │
          ▼
   ┌─────────────────────────────────┐
   │  对每个 sprint:                  │
   │                                 │
   │  Generator ←──────→ Evaluator   │
   │  proposal      contract review  │
   │  (deliverables  (4 维评分门槛)   │
   │   + criteria)                   │
   │       │              ▲          │
   │       │              │          │
   │       ▼              │          │
   │  execute  →  sprint_result      │
   │       │              │          │
   │       └──────► evaluate         │
   │              (60 分以下重试)     │
   └─────────────────────────────────┘
```

**核心创新**：
- **Sprint 合约协商**：写代码前先谈"什么算 done"
- **GAN-inspired**：Generator 与 Evaluator 对抗，避免 self-eval bias
- **4 维评分**：quality / originality / craft / functionality（任一 < 60 拒绝）

V1 实现：`pilot/capability/workforce/harness.py::WorkforceHarness`。

---

## 4. Cognition「单线程写」原则

```python
# pilot/capability/tools/registry.py::ToolRegistry
@dataclass
class ToolSpec:
    name: str
    read_only: bool   # ← 关键标识
    ...

# pilot/runtime/harness.py::HarnessLoop._step_permit_and_execute
read_only_calls = [tc for tc in approved if self.tools.is_read_only(tc.name)]
write_calls     = [tc for tc in approved if not self.tools.is_read_only(tc.name)]

# read 并行
await asyncio.gather(*[exec_one(tc) for tc in read_only_calls])

# write 串行（防止风格冲突）
for tc in write_calls:
    await exec_one(tc)
```

V1 工具集分类：

| Read-only | Write |
|---|---|
| `voice.transcribe` | `doc.create` |
| `im.fetch_thread` | `doc.append` |
| `mentor.summarize` | `canvas.create` |
| `bitable.search` | `slide.generate` |
| | `archive.bundle` |

---

## 5. 协议层：MCP / ACP / A2A

```
┌──────────────────────────┐
│ Cursor / Claude / Trae   │  ← 反向调 V1 工具
└─────────────┬────────────┘
              │ MCP（HTTP/JSON-RPC）
              ▼
┌──────────────────────────┐
│ V1 MCP Server            │  pilot/surface/mcp_server.py
│ /tools/list              │
│ /tools/call              │
│ /resources/list          │
└──────────────────────────┘

┌──────────────────────────┐
│ V1 ACP Server (二期)      │  IDE 客户端可接
└──────────────────────────┘

┌──────────────────────────┐
│ A2A (二期)                │  远程 Agent 委托
└──────────────────────────┘
```

V1 **当下就能做**的：Cursor/Claude/Trae 通过 MCP 调用 V1 工具，反向贡献给评委的 IDE。

---

## 6. SKILL.md cascade（Claude Code / OpenAI Agents SDK 风格）

```
/etc/claude-code/CLAUDE.md            # managed
~/.claude/CLAUDE.md                   # user
<repo>/AGENTS.md                       # project（V1 的 AGENTS.md）
<repo>/.agent-pilot/skills/<name>/SKILL.md
<repo>/AGENTS.local.md                 # gitignored 个人覆盖
```

V1 在 [`pilot/context/agents_md.py`](../pilot/context/agents_md.py) 实现：
- 4 级 cascade 自动发现
- `@./path/to/another.md` include 递归（最多 5 级）
- HTML 注释自动剥离
- 进程级缓存（避免每个 LLM 调用都读盘）

---

## 7. SKILL.md 格式（V1 4 个原生 + 借鉴 lark-cli 29 个）

```markdown
---
name: pilot-doc
version: 1.0.0
description: 何时使用本 skill 的判断逻辑
metadata:
  requires:
    tools: [doc.create, doc.append]
  read_only: false
---

# pilot-doc

## 1. 何时使用
- ✓ 用户要"写文档"
- ✗ 用户只要 PPT（用 pilot-slide）

## 2. 调用流程
1. doc.create(title)   → doc_token
2. doc.append(token)   → markdown 自动生成

## 3. 富媒体
- 图片：![alt](url) 自动上传飞书 Drive
- Mermaid：飞书 Docx 自动渲染
```

---

## 8. 评分维度证据自检

### 创新性 25%

✅ **5 层 Harness 架构**——直接搬 Modern Agent Harness Blueprint 2026 的 5 层
✅ **Claude Code 8 步 loop 内核**——这是 2026 年 Agent 工程的事实标准
✅ **Anthropic 三 Agent GAN harness**——长任务的最新方法论（2026-03 发布）
✅ **MCP 反向暴露**——让外部 AI（Cursor/Claude/Trae）反过来用 V1 的工具
✅ **Cognition 单线程写约束**——避免 Multi-Agent 风格冲突
✅ **CardKit 2.0 70ms 打字机**——飞书最新流式 API
✅ **lark-cli 29 SKILL.md submodule**——飞书官方背书
✅ **5 PPT 模板（Hero/TwoColumn/Cards/List/Quote）**——融合 Gamma 的 card-based + Beautiful.ai 设计规则

### 技术 25%

✅ **5 层单向依赖** + 75 测试守护
✅ **缓存稳定**：SYSTEM_PROMPT_DYNAMIC_BOUNDARY
✅ **Filesystem as working memory**：artifact:// handle
✅ **4 级权限 + 沙箱 + 审计**：Governance 三件套
✅ **OpenTelemetry**：可选启用，5 个核心 span
✅ **CRDT 多端同步**：pycrdt-websocket + 离线 reconcile
✅ **多 LLM Provider** + 429 退避 + Mock 兜底
✅ **pre-commit + ruff + pytest + CI**

### 完整性 50%

✅ **端到端闭环**：IM → 三闸门 → Planner → 三 Agent → 工具 → 归档
✅ **公网可访问**：http://8.136.98.175 上 V1 已上线
✅ **75/75 测试全绿**（含 7 条裁判级 e2e）
✅ **5 分钟 JUDGE_GUIDE** + 短视频脚本 + DEMO_SCRIPT 答辩稿
✅ **PRD 100% 覆盖证明** ([docs/PRD_COVERAGE.md](PRD_COVERAGE.md))
