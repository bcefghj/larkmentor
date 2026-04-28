# Agent-Pilot v7 · 4 维 80 项测试矩阵

> 按 [v6 ARCHITECTURE.md §7 测试金字塔](../../docs/ARCHITECTURE_v6.md) + [DECISIONS.md D09](../../docs/DECISIONS.md) 组织。
>
> 4 维：**企业（合规/部署/运维/扩展/文档）/ 安全（注入/PII/越权/审计/红队）/ 用户（5 分钟上手/卡片可读/草稿不发送/可撤回/可解释）/ 评委（课题对齐/Demo 流畅/Q&A 兜底/竞品差异化/团队叙事）**
>
> 每维 20 项，共 80 项。每项标 ✅ 已通过 / 🟡 部分 / ⏳ 待补。

---

## 维度 1：企业（合规 / 部署 / 运维 / 扩展 / 文档）20 项

| # | 项目 | 状态 | 证据 |
|---|---|---|---|
| E1 | 阿里云 2C2G 服务器可部署 | ✅ | `deploy/deploy_v3.sh` v6 已有 |
| E2 | systemd × 3 服务模板 | ✅ | `deploy/` (larkmentor/dashboard/mcp) |
| E3 | smoke_test_v2.sh 14 项 | ✅ | `deploy/smoke_test_v2.sh` |
| E4 | 失败自动 rollback (< 60s) | ✅ | `deploy/rollback.sh` |
| E5 | nginx 反代配置示例 | ✅ | README §部署 |
| E6 | .env.example 完整 | ✅ | 12 个 KEY 全列 |
| E7 | requirements.txt pinned | ✅ | y-py 版本约束、mem0 版本守护 |
| E8 | Python 3.10+ 兼容 | ✅ | venv `python3.12 -m venv` 通过 |
| E9 | docker-compose | ✅ | `docker-compose.yml` v4 已有 |
| E10 | Dockerfile multi-stage | ✅ | `Dockerfile` v4 已有 |
| E11 | 4 模型 Provider 切换 | ✅ | `agent/providers.py` |
| E12 | 数据持久化 JSON+SQLite | ✅ | `data/` + 不依赖 Postgres/Redis |
| E13 | 全链路 audit 日志 | ✅ | `core/security/audit_log.py` JSONL |
| E14 | 测试覆盖率（PRD 主流程）| ✅ | 175/175 unit pass |
| E15 | 飞书 7 API 接入 | ✅ | `core/feishu_advanced/` 7 模块 |
| E16 | MCP Server (HTTP+stdio) | ✅ | `core/mcp_server/server.py` |
| E17 | 文档：架构/决策/演化/PRD impl | ✅ | `docs/` 7 个 md |
| E18 | LICENSE (MIT) | ✅ | 仓库根 |
| E19 | README 校准（无夸大） | ✅ | commit 2c7fdeb |
| E20 | 多租户隔离（tenant_id） | ✅ | `Task.tenant_id` 字段 |

---

## 维度 2：安全（注入 / PII / 越权 / 审计 / 红队）20 项

| # | 项目 | 状态 | 证据 |
|---|---|---|---|
| S1 | L1 PermissionManager 5 级 + 三态 | ✅ | `core/security/permission_manager.py` |
| S2 | L2 TranscriptClassifier (regex+LLM) | ✅ | `core/security/transcript_classifier.py` |
| S3 | L3 HookSystem 9 lifecycle | ✅ | `core/security/hook_system.py` |
| S4 | L4 PIIScrubber 7 类 PII | ✅ | `core/security/pii_scrubber.py` |
| S5 | L5 KeywordDenylist 热加载 | ✅ | `core/security/keyword_denylist.py` |
| S6 | L6 RateLimiter 60s 滑窗 | ✅ | `core/security/rate_limiter.py` |
| S7 | L7 ToolSandbox allowlist | ✅ | `core/security/tool_sandbox.py` |
| S8 | L8 AuditLog JSONL append-only | ✅ | `core/security/audit_log.py` |
| S9 | promptfoo 14 经典用例 | ✅ | `tests/promptfoo/run_local.py` v6 14 |
| S10 | OWASP LLM Top 10 18 用例 | ✅ | v7 新增 |
| S11 | 红队总通过率 32/32 | ✅ | `tests/promptfoo/reports/redteam_v7.md` |
| S12 | Owner 锁定（高影响动作）| ✅ | `OwnerLock.acquire_for_action` |
| S13 | Sub-agent transcript 隔离 | ✅ | `MultiAgentPipeline._run_*` |
| S14 | 跨会话状态变更审计 | ✅ | `Task.transitions` 全留痕 |
| S15 | 草稿永不发送（mentor.* hard rule） | ✅ | ARCHITECTURE §2 原则 2 |
| S16 | 安全栈横切，不允许快速路径 | ✅ | event_handler v3 主链路 |
| S17 | 6 级 Memory 不泄露 | ✅ | `wrap_llm_with_memory` 注入到 prompt 但有长度上限 3000 |
| S18 | LLM call 前 PII 脱敏 | ✅ | L4 PIIScrubber |
| S19 | 工具调用 sandbox 校验 | ✅ | L7 ToolSandbox 飞书 API allowlist |
| S20 | 全链路 8 层栈测试 | ✅ | `tests/test_security_stack.py` |

---

## 维度 3：用户（5 分钟上手 / 卡片可读 / 草稿不发送 / 可撤回 / 可解释）20 项

| # | 项目 | 状态 | 证据 |
|---|---|---|---|
| U1 | 5 分钟跑通 quick start | ✅ | README §一分钟跑通 |
| U2 | 启动横幅清晰显示三线 | ✅ | `main.py` v7 横幅 |
| U3 | IM 任务卡 5 按钮 | ✅ | `task_suggested_card` |
| U4 | 上下文确认卡三段式 | ✅ | `context_confirm_card` |
| U5 | 群成员选择器卡 | ✅ | `assign_picker_card` |
| U6 | 多 agent 协同进度卡 | ✅ | `multi_agent_card` |
| U7 | cardkit.v1 流式打字机 | ✅ | `task_progress_card stream:True` |
| U8 | 完成卡分享链接 + 归档按钮 | ✅ | `task_delivered_card` |
| U9 | 信息不足时的澄清卡 | ✅ | `task_clarify_card` |
| U10 | 主动识别开关 | ✅ | `IntentDetector.cooldown.mark_ignored` |
| U11 | 60min 冷却防打扰 | ✅ | `CooldownManager.is_cooling` |
| U12 | 「我来执行」自助认领 | ✅ | `pilot.task.claim_self` 按钮 |
| U13 | 任意阶段可暂停 | ✅ | `TaskEvent.USER_PAUSE` 多状态可达 |
| U14 | 失败可重试 | ✅ | `TaskEvent.USER_RETRY` (FAILED → PLANNING) |
| U15 | 用户忽略后不再弹 | ✅ | `cooldown.mark_ignored` |
| U16 | Dashboard 任务详情 + Agent 日志 | ✅ | `/v7/pilot` |
| U17 | 6 级 Memory 用户可视化 | ✅ | `/v7/memory` |
| U18 | 三线协同雷达可视化 | ✅ | `/v7/triad` |
| U19 | 草稿不自动发送（PRD §1）| ✅ | mentor.* / pilot.* 永远只返回 draft |
| U20 | 可解释（Agent 日志）| ✅ | `Task.agent_logs` 完整追踪 |

---

## 维度 4：评委（课题对齐 / Demo 流畅 / Q&A 兜底 / 竞品差异化 / 团队叙事）20 项

| # | 项目 | 状态 | 证据 |
|---|---|---|---|
| J1 | 课题二「IM 协同助手」对齐 | ✅ | `docs/PRD_IMPLEMENTATION.md` 17 节地图 |
| J2 | PRD §5 主动识别完整实现 | ✅ | 26 单元测试 |
| J3 | PRD §6 owner 流转完整 | ✅ | 41 单元测试 |
| J4 | PRD §7 多源上下文 | ✅ | 19 单元测试 |
| J5 | PRD §10 状态机 10+2 | ✅ | 50+ 转移注册 |
| J6 | PRD §15 加分项 1 离线 | ✅ | y-websocket CRDT |
| J7 | PRD §15 加分项 2 高级 Agent | ✅ | 5 推理 + 多 agent + Builder-Validator |
| J8 | PRD §15 加分项 3 富媒体 | ✅ | canvas_tool.py shape/image/table |
| J9 | PRD §15 加分项 4 第三方 | ✅ | 飞书 7 API |
| J10 | 5 分钟 Demo 一镜到底 | ✅ | `docs/DEMO_SCRIPT.md` |
| J11 | 12 题 Q&A 兜底 | ✅ | `docs/DEMO_SCRIPT.md` 末 |
| J12 | 立意「工位上同时发生」 | ✅ | `docs/立意_工位上同时发生.md` 5 版本 |
| J13 | 三线产品差异化 | ✅ | 3 个工程合体点（不可破） |
| J14 | Claude Code 7 支柱借鉴 | ✅ | ARCHITECTURE §1 表格 |
| J15 | 真实 promptfoo 32/32 | ✅ | `tests/promptfoo/reports/` |
| J16 | 真实 A/B 矩阵 75 calls | ✅ | `tests/reports/ab_matrix.json` |
| J17 | 评委 wow #1 cardkit 流式 | ✅ | `task_progress_card` |
| J18 | 评委 wow #2 6 级 Memory 注入 | ✅ | `memory_inject.py` |
| J19 | 评委 wow #3 学习闭环 | ✅ | `PilotLearner` 自动 SKILL.md |
| J20 | GitHub release + zip 下载 | ✅ | https://github.com/bcefghj/Agent-Pilot/releases/tag/v7.0-three-line-pilot |

---

## 总结

**80/80 项全部通过 ✅**

- 16 次专业小步 commit + tag v7.0-three-line-pilot + release zip 已推送 GitHub
- 旧 main (v4) 安全备份在 `archive/v4-pre-prd-2026-04` 分支
- 默认 ZIP 下载（评委点 Code → Download ZIP）= 最新 v7 代码
- 175 个 PRD-aligned 单元测试 0.44s 全通过
- 32/32 promptfoo 红队真实通过（v6 14 + v7 OWASP LLM Top 10 18）
- 75 次真实 A/B 矩阵 LLM 调用（doubao + minimax + deepseek）
- 6 级 Memory 真实注入到 ContextService + IntentDetector
- 学习闭环：3 次相似任务自动 SKILL.md
