# LarkMentor v2 升级部署手册

> 从 v1 升级到 v2（Claude Code 7 支柱 + 8 层栈补完 + Recovery Card）
> 阿里云 2C2G 环境
> 风险：低（v2 完全向后兼容 v1，119+pytest 全过 + 新增 54 测试也全过）
> 回滚：bash rollback.sh（< 60 秒）

---

## 0. 升级前置检查清单

```bash
# 在本地仓库 (larkmentor/40_code/project) 跑：
PYTHONPATH=. pytest -q  # 必须 173+ passed
```

预期：

```
153+ passed (不含 recovery_card 因为它依赖 mentor_write LLM)
+ recovery_card 12 (单独跑)
= 173+ 全过
```

如果有 fail，**不要**部署。先在本地修复。

---

## 1. v2 的 9 项核心代码改动

| # | 改动 | 影响范围 | 回滚复杂度 |
|---|---|---|---|
| 1 | 新增 core/runtime/ 4 文件 | 仅新增 | 删目录即可 |
| 2 | event_handler 切到 v3 | 主链路 | 设环境变量 LARKMENTOR_USE_V3_MAIN_CHAIN=0 |
| 3 | classifier 调 KB（待 step11 已做注入）| 6 维分类 | 可关 LARKMENTOR_AUTO_INJECT_MEMORY=0 |
| 4 | 新增 recovery_card.py | 仅新增 | 不调用即可 |
| 5 | 补完 KeywordDenylist/RateLimiter/ToolSandbox | 安全栈 | 仅作用于 v3 主链路 |
| 6 | user_state 加 fcntl + atomic | 持久化 | 兼容旧文件 |
| 7 | mentor 4 模块 → SkillLoader 注册 | runtime | 调 register_all 才生效 |
| 8 | MCP 加 4 新工具 | MCP 接口 | 不调用即可 |
| 9 | LLM 调用加 6 级 memory 注入 | 全 LLM 调用 | 关 LARKMENTOR_AUTO_INJECT_MEMORY=0 |

**关键**：所有改动**默认开启**但**可一键关闭**——通过环境变量。

---

## 2. 升级步骤（约 10 分钟）

### Step A · 本地最后验证（5 分钟）

```bash
cd larkmentor/40_code/project
PYTHONPATH=. pytest -q
# 必须 173+ passed
```

### Step B · 推送代码到服务器

```bash
# 假设服务器是 root@118.178.242.26
cd larkmentor/60_deploy
bash deploy_lark_mentor.sh
# 内部会：
#   1. scp 代码到 /opt/larkmentor_v2/
#   2. 装依赖 (pip install -r requirements.txt)
#   3. 启动新 systemd 服务（不停旧的）
#   4. 跑 smoke
```

### Step C · 跑 smoke 15 项

```bash
bash smoke_test.sh
# 预期 15/15 PASS
```

如果 smoke 失败：
```bash
bash rollback.sh
# 60 秒内回到 v1
```

### Step D · 切流量（冷切换）

```bash
# 修改 nginx 路由：将 /lark/event → v2 服务
# 旧 v1 服务保持运行 24 小时（备份）
```

### Step E · 24 小时观察

```bash
# 监控
watch -n 60 'curl -s http://118.178.242.26/dashboard/health | jq'
tail -f /var/log/larkmentor_v2/bot.log
```

观察指标：
- 错误率 < 0.5%
- p95 延迟 < 200ms
- pytest 跨夜 cron 仍通过

### Step F · 退役 v1（24 小时后）

```bash
systemctl stop larkmentor_v1-bot
systemctl disable larkmentor_v1-bot
# 数据保留在 /opt/larkmentor_v1/data 备份
```

---

## 3. 环境变量调优

```bash
# /etc/systemd/system/larkmentor_v2-bot.service.env
LARKMENTOR_USE_V3_MAIN_CHAIN=1     # 默认 1，走 v3 主链路。设 0 则回 v1 行为
LARKMENTOR_AUTO_INJECT_MEMORY=1    # 默认 1，自动注入 6 级 memory。设 0 则关闭
LARKMENTOR_RECOVERY_CARD_ENABLED=1 # 默认 1（待加，本期 always on）
LARKMENTOR_RATE_LIMIT_QPM=60       # 默认 60 QPM/user
```

---

## 4. 验证清单（部署后必做）

| 项 | 验证命令 | 预期 |
|---|---|---|
| 1 systemd 运行 | `systemctl is-active larkmentor_v2-bot` | active |
| 2 dashboard 可达 | `curl -sI http://118.178.242.26/dashboard` | 200 |
| 3 mcp 可达 | `curl -sI http://118.178.242.26/mcp/tools` | 200 |
| 4 主页可达 | `curl -sI http://118.178.242.26/` | 200 |
| 5 飞书事件回调 | 私聊 Bot 发"我的状态" | 收到响应 |
| 6 6 级 memory 注入生效 | `curl ... memory_resolve` | tiers_present 包括 user/enterprise |
| 7 8 层栈生效 | `curl ... classify_readonly` 发恶意 | 返回 P3 + reason |
| 8 草稿不发送 | 主动发"帮我看：测试" | 返回卡片，不发出去 |
| 9 Recovery Card | `开启专注 + 等几条消息 + 结束专注` | 收到双线 Card |
| 10 审计日志 | `tail /opt/larkmentor_v2/data/audit.jsonl` | 有新事件 |
| 11 pytest 跨夜 | cron daily | 仍 173+ pass |
| 12 24h 错误率 | grep ERROR /var/log/larkmentor_v2/bot.log | wc -l | < 5 |
| 13 24h 内存 | `free -h` | <80% |
| 14 24h 磁盘 | `df -h /opt/larkmentor_v2/` | <80% |
| 15 24h 重启 | `systemctl status` | 无 unexpected restart |

---

## 5. 故障排除

| 症状 | 原因 | 修复 |
|---|---|---|
| 启动失败：ModuleNotFoundError | 依赖未装 | `pip install -r requirements.txt` |
| 6 级 memory 未注入 | data/flow_memory_md/ 没文件 | 创建 enterprise.md（哪怕空文件）|
| Recovery Card 不弹 | focus 期间无 P0/P1/P2 | 正常（设计）|
| MCP classify_readonly 报 user_not_found | 错误期望（已修复）| 自动创建 user |
| RateLimit 误伤 | QPM 太低 | 调 LARKMENTOR_RATE_LIMIT_QPM=120 |

---

## 6. 一键回滚

```bash
bash rollback.sh
```

执行：
1. 停 v2 systemd
2. nginx 切回 v1
3. 启 v1 systemd（之前一直在跑作为备份）
4. 验证 smoke 15/15

预计 60 秒内完成。

---

## 7. 跨委 24h 安全验证（决赛前必做）

```bash
# 5/9-5/10 跨夜
# 持续 24h cron：
0 * * * * cd /opt/larkmentor_v2 && bash 60_deploy/smoke_test.sh > /var/log/larkmentor_v2/smoke_$(date +\%H).log 2>&1
```

预期 24/24 次 smoke 全过。

---

## 8. 回归测试（升级后周一加跑）

```bash
# 在阿里云上跑全量 pytest
cd /opt/larkmentor_v2
PYTHONPATH=. pytest -q
# 预期 173+ passed

# Promptfoo 红队
cd tests/promptfoo
promptfoo eval -c larkmentor.yaml
# 预期 ≥ 14/14 通过
```

---

## 9. 决赛日演示前的最后检查（5/14 凌晨）

```bash
# 1. 跑 smoke
bash smoke_test.sh
# 必须 15/15 全过

# 2. 跑 pytest
PYTHONPATH=. pytest -q
# 必须 173+ passed

# 3. 私聊 Bot 试 5 个核心场景
# - 我的状态 → 应返回当前状态
# - 帮我看：紧急测试 → 应返回 3 版草稿
# - 任务确认：测试 → 应返回澄清问题
# - 开启专注 + 结束专注 → 应弹 Recovery Card
# - MCP curl classify_readonly → 应返回 P3 + reason

# 4. 检查 dashboard 可达
open http://118.178.242.26/dashboard

# 5. 备份 audit 日志（万一）
scp root@118.178.242.26:/opt/larkmentor_v2/data/audit.jsonl backup/audit_5_14.jsonl
```

---

*最后更新：2026-04-19*
