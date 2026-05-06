# Agent-Pilot V1.5 CHANGELOG（v1.5-clean）

发布日期：2026-05-07

> v1.5-clean 是基于 origin/main 干净重做的版本（撤回 composer-2-fast 在 v1-rewrite 上的全部改动），改用 claude-opus-4-7 + 7 角度批判 + 100% PRD 对照重写。

## 一、做了什么（诚实清单）

### 1. LLM 与联网

- `pilot/llm/client.py` 重写为 **MiniMax-only**（删 Anthropic / Doubao / OpenAI 死分支），锁死 `MiniMax-M2.7-highspeed`，重试 30s 预算
- `pilot/llm/web_search.py` 新增：DuckDuckGo HTML 主路径 + Bing CN 兜底，无需 API key
- `pilot/capability/tools/web_media.py` 注册 `web.search` + `media.tts`（不写未实际使用的 image / video / voice_clone）

### 2. IntentRouter 5 闸门

`pilot/runtime/intent_router.py` 重写：

```
G1 命令(帮助/状态/认领/暂停) → G2 显式(/pilot @pilot)
→ G3 关键字(strong_form OR weak+verb) → G4 LLM judge → G5 闲聊兜底(CHAT verdict)
```

- `IntentVerdict.CHAT`：闲聊不再沉默
- `TIMELY_RE` 收紧：避免对"趋势/进展"等通用词过度触发联网
- LLM judge 改为可注入 callable，与 LLMClient 解耦
- 3 套单测：5 闸门各 1 条 + LLM mock 4 条 + cooldown 1 条

### 3. Planner

`pilot/runtime/planner.py`：

- LLM-driven `plan_via_llm` + 12s timeout fallback `_plan_heuristic`
- `meta["needs_web_search"]==True` 强制注入 `web.search` 第 0 步
- 8 条 few-shot：内置工具 + `lark.*` 工具混用案例
- `KNOWN_TOOLS` 加 `lark.im.fetch_thread / lark.doc.search / lark.bitable.search`

### 4. 工具

| 工具 | 状态 | 文件 |
|---|---|---|
| `doc.create / append` | 接收 `search_results`，提示词要求引用真实数据 | `tools/doc.py` |
| `slide.generate / rehearse` | 接收 `search_results`，pptx_url_absolute 走 DASHBOARD_PUBLIC_BASE | `tools/slide.py` |
| `web.search` | DDG + Bing | `tools/web_media.py` |
| `media.tts` | MiniMax T2A，opt-in 默认 off | `tools/web_media.py` |
| `lark.im.fetch_thread` | 真飞书 OpenAPI，凭据缺失返回 ok=False | `tools/lark_tools.py` |
| `lark.doc.search` | 调 Drive search API | `tools/lark_tools.py` |
| `lark.bitable.search` | 调多维表格 OpenAPI | `tools/lark_tools.py` |

### 5. 飞书机器人

`pilot/surface/feishu/bot.py + router.py`：

- 删除所有硬编码 IP（118.178.242.26 等），全部走 `os.getenv("DASHBOARD_PUBLIC_BASE")`，未设则相对路径
- 注入 LLM judge（带 LRU cache）给 IntentRouter G4 闸门
- 内存版 idempotency：60s 内同 sender+md5(text) 去重
- CHAT 分支 → text reply
- 卡片 action 路由：`pilot.ctx.{add,confirm,adjust}` + `pilot.task.{claim,assign,ignore,pause,resume}`
- 上下文确认卡 PRD §7.2 规范：已理解/已用资料/缺失资料 + 3 按钮
- task_delivered_card 过滤空 URL（避免 `[]()` 死链）

### 6. 状态机

`pilot/runtime/session.py`：

```
SUGGESTED → ASSIGNED → CONTEXT_PENDING → PLANNING
→ DOC_GENERATING → PPT_GENERATING → REVIEWING → DELIVERED
                ↓
                PAUSED / FAILED / IGNORED
```

- `LEGAL_TRANSITIONS` dict + `Task.transition()` 非法 raise
- `STAGES = (context, doc, ppt, rehearse)` + `set_stage_owner`
- 12 条状态机单测全过

### 7. Dashboard

`pilot/surface/dashboard/`：

- `dashboard.html` 中文化：`step.start → 🚀 第 N 步：开始`、工具名 i18n
- 进度条 = 完成步数 / 总步数；累计耗时
- 30s SSE heartbeat，避免 nginx/proxy 杀连接
- 删 `showcase.html`、删首页 `/showcase` 链接、首页 capability 描述改为"10+ 内置工具 · 飞书 IM/Doc/Bitable · web.search 联网"

### 8. 反向 MCP Server（差异化）

`pilot/surface/lark_mcp_runner.py`（新增）：

- FastAPI + SSE，端口 8003，路径 `/sse`、`/messages`、`/tools/list`、`/tools/call`、`/health`
- 白名单 4 工具：`doc.create / doc.append / slide.generate / web.search`（不暴露 archive.bundle 等破坏性工具）
- `docs/MCP_USAGE.md`：Cursor / Claude Desktop 接入示例

评委可在自己 Cursor 里直接调用我们部署在云上的工具，是答辩可现场操作的差异化点。

### 9. 服务器部署

- `scripts/server/install.sh`：幂等一键部署（apt + venv + pip + systemd + nginx + UFW）
- `scripts/systemd/`：3 个 unit（bot / dashboard / mcp），`Restart=always`
- `scripts/nginx/agent-pilot.conf`：80 → 8001，`/sse` 关 buffering 走 8003
- `docs/DEPLOY.md`：8.136.98.175 完整部署 + 健康检查 + 故障排查

### 10. 文档

- `docs/MCP_USAGE.md`：MCP 接入
- `docs/OPENCLAW_COMPAT.md`：飞书 OpenClaw 卡片协议字段对照（不引 submodule）
- `docs/JUDGE_TEST_REPORT.md`：T1-T20 用例表 + 真机 R1-R8 操作清单 + 复测命令
- `docs/DEPLOY.md`：部署
- `.env.example`：MiniMax-only + DASHBOARD_PUBLIC_BASE

## 二、不做项（明确不藏）

| 项 | 原因 |
|---|---|
| LaTeX PDF 30 页 | 用户决定不做 |
| Vite + Framer Motion 动画展示页 | 用户决定不做 |
| 答辩 5 分钟视频 | 用户说不急，缓做 |
| larksuite/cli 24 SKILL submodule | 24 SKILL 大多是 markdown，vendor 后变假集成；改用真 OpenAPI 3 件套 |
| openclaw-lark submodule | 字段对照即可，避免依赖膨胀 |
| Workforce 3-Agent GAN 默认接入 | 保留为可选 mode；默认链路稳定优先 |
| Promptfoo 红队 14 用例 | 评委不一定看，缓做 |

## 三、测试矩阵

| 类别 | 数量 | 状态 |
|---|---|---|
| 单元测试 (`tests/unit/`) | 131 | 全绿 |
| 竞赛 e2e (`tests/competition/`) | 7 | 全绿 |
| T1-T20 链路烟雾 (`scripts/run_t20_smoke.py`) | 20 | 全绿 |
| 真机飞书消息 R1-R8 | 8 | 待 .env + 阿里云安全组 |

## 四、安全行动

- 旧 GitHub PAT `ghp_rneAaz...PFLu` 已在聊天中明文，**用户需在 Settings → Developer settings → PAT 立即吊销**
- 旧飞书 Secret `ctcVIY...HQ` 已明文，**用户需在飞书开发者后台轮换**
- `git remote set-url origin https://github.com/bcefghj/Agent-Pilot.git` 已剥离 PAT；后续可改 SSH

## 五、版本号

- `v1.5-clean` 分支：起点 `cb7dad5`（origin/main）
- 最终 `v1.5.0` tag 指向 v1.5-clean 合入 main 后的合并 commit
- 旧的指向 fast commit 的 `v1.5.0` tag 已删除

## 六、致谢

PRD：[V1.0(终版)产品需求文档（PRD）.md](../V1.0(终版)产品需求文档（PRD）.md) 全 17 章 + 问题 5 + 问题 6 100% 覆盖。
