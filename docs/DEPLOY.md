# Agent-Pilot V1.5 部署指南

目标服务器：`8.136.98.175`（Ubuntu 22.04 / 4vCPU / 8 GiB / root）

## 0. 阿里云 ECS 安全组（必做，否则 80 不通）

服务器 OS 防火墙（UFW）已放开 22/80/443，但**阿里云 ECS 实例还有云端安全组**，必须在控制台再开一次：

1. 阿里云控制台 → 云服务器 ECS → 实例 `8.136.98.175` → 「安全组」标签
2. 选当前安全组 → 入方向 → 手动添加：
   - 协议：`TCP`，端口：`80/80`，授权对象：`0.0.0.0/0`，描述：`HTTP`
   - 协议：`TCP`，端口：`443/443`，授权对象：`0.0.0.0/0`，描述：`HTTPS`（如启用）
3. 不要开放 8001/8002/8003，它们只走 nginx 反代

> 现象：服务器内 `curl http://localhost` 返回 200，但本地机 `curl http://8.136.98.175` `Empty reply` → 100% 是云安全组没开。

## 1. 一键安装

```bash
ssh root@8.136.98.175    # 密码：AgentPilot666

# 拉取并执行
curl -fsSL https://raw.githubusercontent.com/bcefghj/Agent-Pilot/v1.5-clean/scripts/server/install.sh | bash
```

或先 clone 再执行：

```bash
git clone -b v1.5-clean https://github.com/bcefghj/Agent-Pilot.git /opt/agent-pilot
bash /opt/agent-pilot/scripts/server/install.sh
```

`install.sh` 会：

1. apt 装 python3.11 / redis / nginx / ufw / 中文字体
2. 创建 venv + `pip install -e .[bot,dashboard]`
3. 拷贝 `.env.example` → `.env`（首次）
4. 安装 3 个 systemd unit
5. 配置 nginx 反代 `/`→ :8001、`/sse`→ :8003
6. UFW：开 22/80/443，封 8001/8002/8003
7. 启动 dashboard + mcp（bot 等 .env 填好后启）

## 2. 填写 `.env`

```bash
nano /opt/agent-pilot/.env
```

必须填：

```ini
FEISHU_APP_ID=cli_a968cdd5fbf8dcc4
FEISHU_APP_SECRET=<在飞书开发者后台轮换后的新 secret>
MINIMAX_API_KEY=<MiniMax 控制台的 API Key>
MINIMAX_GROUP_ID=<MiniMax Group ID>
DASHBOARD_PUBLIC_BASE=http://8.136.98.175
```

> ⚠️ 旧 secret `ctcVIY...HQ` 已在聊天明文出现，**必须**在飞书开发者后台「凭证与基础信息」轮换。

## 3. 启动 bot

```bash
systemctl start agent-pilot-bot
systemctl status agent-pilot-bot agent-pilot-dashboard agent-pilot-mcp
```

## 4. 健康检查

```bash
curl http://8.136.98.175/health           # → {"status":"healthy",...}
curl http://8.136.98.175/api/sessions      # → 最近 sessions JSON
curl http://8.136.98.175/sse              # → SSE ping 流（Ctrl-C 停）
curl http://8.136.98.175/tools/list | jq   # → 反向 MCP 4 工具
```

浏览器：

- http://8.136.98.175/ Dashboard
- http://8.136.98.175/dashboard 任务实时进度

## 5. 日志

```bash
tail -f /opt/agent-pilot/logs/bot.log
tail -f /opt/agent-pilot/logs/dashboard.log
tail -f /opt/agent-pilot/logs/mcp.log
journalctl -u agent-pilot-bot -f
```

## 6. 飞书后台配置

在飞书开发者后台 → 你的 App → 事件订阅：

- 订阅模式：**长连接**（WebSocket）
- 不需要配 webhook URL（用 lark-oapi WS 客户端）
- 必选权限：
  - `im:message`（接收用户消息）
  - `im:message:send_as_bot`（回复消息 + 卡片）
  - `docx:document`（创建 / 编辑 Docx）
  - `drive:drive`（文件夹定位、Drive search）
  - `bitable:app`（多维表格读，可选）

确保把 `FEISHU_APP_ID / FEISHU_APP_SECRET` 填进 `.env` 后，重启 bot。

## 7. 部署后验证（T1-T20 自查清单）

参考 [`docs/JUDGE_TEST_REPORT.md`](JUDGE_TEST_REPORT.md)（Phase 4 输出）。

## 8. 升级

```bash
cd /opt/agent-pilot
git pull
.venv/bin/pip install -e ".[bot,dashboard]"
systemctl restart agent-pilot-bot agent-pilot-dashboard agent-pilot-mcp
```

或重新跑一遍 `scripts/server/install.sh`（幂等）。

## 9. 卸载

```bash
systemctl disable --now agent-pilot-{bot,dashboard,mcp}
rm -f /etc/systemd/system/agent-pilot-*.service
rm -f /etc/nginx/sites-enabled/agent-pilot.conf /etc/nginx/sites-available/agent-pilot.conf
systemctl reload nginx
rm -rf /opt/agent-pilot
```

## 10. 故障排查

| 症状 | 排查 |
|---|---|
| bot 不响应 | `journalctl -u agent-pilot-bot -n 100`；多半是 `.env` 未填 / 飞书 secret 失效 |
| dashboard 空白 | `curl http://localhost:8001/health`；`systemctl status agent-pilot-dashboard` |
| MCP /sse 502 | `systemctl status agent-pilot-mcp`；nginx error log `/var/log/nginx/error.log` |
| 飞书消息不来 | 飞书后台 → 事件订阅 → 启用长连接；检查 IP 白名单是否启用 |
| 图片 / PPT 链接死 | `DASHBOARD_PUBLIC_BASE` 未设或不对；`.env` 改完重启 bot |
