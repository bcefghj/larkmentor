#!/usr/bin/env bash
# Agent-Pilot V1.5 · 服务器一键部署（Ubuntu 22.04 / Debian 12）
# Idempotent：可重复执行，已存在的步骤会跳过。
#
# 用法（在服务器 root）：
#   curl -fsSL https://raw.githubusercontent.com/bcefghj/Agent-Pilot/v1.5-clean/scripts/server/install.sh | bash
# 或：
#   bash /opt/agent-pilot/scripts/server/install.sh

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/agent-pilot}"
APP_USER="${APP_USER:-root}"
# Ubuntu 22.04 自带 python3.10；如需 3.11 设 PY=python3.11 并自行装 deadsnakes PPA
PY="${PY:-python3}"
REPO="${REPO:-https://github.com/bcefghj/Agent-Pilot.git}"
BRANCH="${BRANCH:-v1.5-clean}"

log() { echo -e "\033[1;32m[install]\033[0m $*"; }
warn() { echo -e "\033[1;33m[warn]\033[0m $*"; }

# ── 1. 系统包 ──
log "apt 安装基础包..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    curl ca-certificates git build-essential pkg-config \
    python3 python3-venv python3-dev python3-pip \
    redis-server nginx ufw \
    fonts-noto-cjk fonts-noto-color-emoji

systemctl enable --now redis-server || true

# ── 2. 拉取代码 ──
if [ ! -d "$APP_DIR/.git" ]; then
    log "首次 clone 到 $APP_DIR (branch=$BRANCH)..."
    git clone --branch "$BRANCH" --depth 1 "$REPO" "$APP_DIR"
else
    log "更新已有仓库 $APP_DIR..."
    cd "$APP_DIR"
    git fetch origin "$BRANCH"
    git checkout "$BRANCH" || git checkout -B "$BRANCH" "origin/$BRANCH"
    git reset --hard "origin/$BRANCH"
fi

cd "$APP_DIR"

# ── 3. Python 虚拟环境 ──
if [ ! -d "$APP_DIR/.venv" ]; then
    log "创建 venv..."
    "$PY" -m venv "$APP_DIR/.venv"
fi
# shellcheck disable=SC1091
source "$APP_DIR/.venv/bin/activate"
pip install -U pip wheel setuptools
log "安装 Python 依赖..."
pip install -e ".[bot,dashboard]" || pip install -e .

# ── 4. .env 模板 ──
if [ ! -f "$APP_DIR/.env" ]; then
    log "拷贝 .env.example → .env，请填飞书 + MiniMax 密钥"
    cp .env.example .env
    warn "记得编辑 $APP_DIR/.env：FEISHU_APP_ID / FEISHU_APP_SECRET / MINIMAX_API_KEY / DASHBOARD_PUBLIC_BASE"
else
    log ".env 已存在，跳过"
fi

# ── 5. 数据目录 ──
mkdir -p "$APP_DIR/data" "$APP_DIR/data/artifacts" "$APP_DIR/logs"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/data" "$APP_DIR/logs"

# ── 6. systemd units ──
log "安装 systemd unit..."
install -m 0644 scripts/systemd/agent-pilot-bot.service       /etc/systemd/system/
install -m 0644 scripts/systemd/agent-pilot-dashboard.service /etc/systemd/system/
install -m 0644 scripts/systemd/agent-pilot-mcp.service       /etc/systemd/system/
systemctl daemon-reload

# ── 7. nginx ──
log "配置 nginx..."
install -m 0644 scripts/nginx/agent-pilot.conf /etc/nginx/sites-available/agent-pilot.conf
ln -sf /etc/nginx/sites-available/agent-pilot.conf /etc/nginx/sites-enabled/agent-pilot.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# ── 8. 防火墙 ──
log "UFW 规则..."
ufw allow 22/tcp  || true
ufw allow 80/tcp  || true
ufw allow 443/tcp || true
ufw deny  8001/tcp || true
ufw deny  8002/tcp || true
ufw deny  8003/tcp || true
ufw --force enable || true

# ── 9. 启动 ──
log "启动 Agent-Pilot 三件套..."
systemctl enable --now agent-pilot-dashboard.service
systemctl enable --now agent-pilot-mcp.service
# bot 最后启动（依赖 .env 已配）
if grep -q "your_app_secret_here" "$APP_DIR/.env" 2>/dev/null || ! grep -q "FEISHU_APP_SECRET=." "$APP_DIR/.env"; then
    warn ".env 还没填飞书 secret，bot 暂不启动；编辑后跑：systemctl start agent-pilot-bot"
else
    systemctl enable --now agent-pilot-bot.service
fi

log "完成！健康检查："
echo "  curl http://localhost/health"
echo "  curl http://localhost/api/health"
echo "  curl http://localhost:8003/health"
echo "  systemctl status agent-pilot-*.service"
