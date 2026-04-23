#!/usr/bin/env bash
# LarkMentor v2 (Agent-Pilot) 部署脚本
#
# 假设：
#   - 服务器地址 / 密码已经写到 ~/.ssh/config 或下面的 HOST / PW 变量
#   - 本地在 larkmentor_github 根目录（含 main.py / dashboard/ / core/ 等）
#
# 完整流程：
#   0. 本地 pytest 必须 100% 通过
#   1. 打 tarball（排除 .venv / data / .env / __pycache__）
#   2. scp 上传到 /opt/larkmentor_v2_release.tar.gz
#   3. 远端：备份老版 data → 解压 → 复制旧 .env 和持久化数据
#   4. 创建 venv 并装依赖（含 y-py / websockets）
#   5. 写/更新 4 个 systemd 服务：
#       - larkmentor           （飞书 Bot 主进程）
#       - larkmentor-dashboard （FastAPI :8001，含 Pilot + Sync WS）
#       - larkmentor-mcp       （MCP HTTP :8767）
#       - larkmentor-artifacts （静态产物 Nginx 由 /artifacts 暴露，无需独立 service）
#   6. 冷切换 + smoke_test → 失败自动回滚

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${HOST:-118.178.242.26}"
USER="${REMOTE_USER:-root}"
PW="${REMOTE_PW:-bcefghj@Github666}"
REMOTE_BASE="/opt/larkmentor_v2"
REMOTE_TAR="/opt/larkmentor_v2_release.tar.gz"

step() { printf "\n\033[1;36m== %s ==\033[0m\n" "$*"; }

# ── 0. Local pytest gate ──
step "0/6 本地 pytest 必须 100% 通过"
( cd "$ROOT" && PYTHONPATH=. python3 -m pytest tests/ -q \
    --ignore=tests/e2e --ignore=tests/simulator ) || {
    echo "[FAIL] pytest 失败，拒绝部署"
    exit 1
}

# ── 1. Build tarball ──
step "1/6 打包源码"
TARBALL="$ROOT/.larkmentor_v2.tar.gz"
( cd "$ROOT" && COPYFILE_DISABLE=1 tar \
    --exclude='./data' \
    --exclude='./.venv' \
    --exclude='./.env' \
    --exclude='./logs' \
    --exclude='./mobile_desktop/build' \
    --exclude='./mobile_desktop/.dart_tool' \
    --exclude='**/__pycache__' \
    --exclude='**/.pytest_cache' \
    --exclude='**/*.pyc' \
    --exclude='**/.DS_Store' \
    -czf "$TARBALL" . 2>/dev/null )
ls -lh "$TARBALL"

# ── 2. Upload ──
step "2/6 上传 tarball (scp)"
if command -v sshpass >/dev/null; then
    sshpass -p "$PW" scp -o StrictHostKeyChecking=no "$TARBALL" "$USER@$HOST:$REMOTE_TAR"
else
    echo "[warn] sshpass 未安装，手动输入服务器密码："
    scp -o StrictHostKeyChecking=no "$TARBALL" "$USER@$HOST:$REMOTE_TAR"
fi

# ── 3-5. Remote setup ──
step "3/6 远端：解压 + 迁移数据 + 装依赖 + 写 systemd"
REMOTE_SCRIPT=$(cat <<'EOF'
set -e
TS=$(date +%Y%m%d_%H%M%S)
BACKUP=/root/larkmentor_v2_backup_$TS
BASE=/opt/larkmentor_v2
TAR=/opt/larkmentor_v2_release.tar.gz

mkdir -p $BACKUP
if [ -d $BASE/data ]; then
    cp -r $BASE/data $BACKUP/data || true
fi
if [ -f $BASE/.env ]; then
    cp $BASE/.env $BACKUP/.env || true
fi

mkdir -p $BASE
cd $BASE
tar -xzf $TAR
echo '[ok] extracted'

# Carry over .env if it already existed
if [ -f $BACKUP/.env ]; then
    cp $BACKUP/.env $BASE/.env
    echo '[ok] carried over .env'
elif [ -f /opt/larkmentor/.env ]; then
    cp /opt/larkmentor/.env $BASE/.env
    echo '[ok] reused .env from v1'
fi

# Carry over persistent data
mkdir -p $BASE/data
if [ -d $BACKUP/data ]; then
    cp -r $BACKUP/data/* $BASE/data/ 2>/dev/null || true
elif [ -d /opt/larkmentor/data ]; then
    cp -r /opt/larkmentor/data/* $BASE/data/ 2>/dev/null || true
fi

# venv + deps
python3 -m venv $BASE/.venv
$BASE/.venv/bin/pip install --upgrade pip --quiet
$BASE/.venv/bin/pip install -r $BASE/requirements.txt --quiet
echo '[ok] deps installed'

# ── systemd units ──
cat > /etc/systemd/system/larkmentor-v2.service <<UNIT
[Unit]
Description=LarkMentor v2 Feishu Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$BASE
Environment="PYTHONPATH=$BASE"
EnvironmentFile=-$BASE/.env
ExecStart=$BASE/.venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/larkmentor-v2-dashboard.service <<UNIT
[Unit]
Description=LarkMentor v2 Dashboard + Sync WebSocket
After=network.target

[Service]
Type=simple
WorkingDirectory=$BASE
Environment="PYTHONPATH=$BASE"
EnvironmentFile=-$BASE/.env
ExecStart=$BASE/.venv/bin/uvicorn dashboard.server:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/larkmentor-v2-mcp.service <<UNIT
[Unit]
Description=LarkMentor v2 MCP HTTP Server
After=network.target

[Service]
Type=simple
WorkingDirectory=$BASE
Environment="PYTHONPATH=$BASE"
EnvironmentFile=-$BASE/.env
ExecStart=$BASE/.venv/bin/python -m core.mcp_server.server --transport http --port 8767
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable larkmentor-v2.service larkmentor-v2-dashboard.service larkmentor-v2-mcp.service

# ── Cold switch: stop old, start new ──
systemctl stop larkmentor.service larkmentor-dashboard.service larkmentor-mcp.service 2>/dev/null || true
systemctl restart larkmentor-v2.service
systemctl restart larkmentor-v2-dashboard.service
systemctl restart larkmentor-v2-mcp.service
sleep 3

# ── Smoke test ──
FAILED=0
curl -sf http://127.0.0.1:8001/health >/dev/null || FAILED=1
curl -sf http://127.0.0.1:8001/api/pilot/scenarios >/dev/null || FAILED=1
curl -sf http://127.0.0.1:8001/sync/health >/dev/null || FAILED=1
curl -sf http://127.0.0.1:8767/tools >/dev/null || FAILED=1

if [ "$FAILED" -eq 1 ]; then
    echo '[FAIL] smoke test failed, rolling back'
    systemctl stop larkmentor-v2.service larkmentor-v2-dashboard.service larkmentor-v2-mcp.service
    systemctl start larkmentor.service larkmentor-dashboard.service larkmentor-mcp.service 2>/dev/null || true
    exit 1
fi

echo '[ok] v2 deployed, smoke tests passed'
EOF
)

if command -v sshpass >/dev/null; then
    sshpass -p "$PW" ssh -o StrictHostKeyChecking=no "$USER@$HOST" "$REMOTE_SCRIPT"
else
    ssh -o StrictHostKeyChecking=no "$USER@$HOST" "$REMOTE_SCRIPT"
fi

step "4/6 更新 nginx 反代（WebSocket /sync/ws + 静态 /artifacts）"
REMOTE_NGINX=$(cat <<'EOF'
cat > /etc/nginx/conf.d/larkmentor_v2.conf <<NGINX
server {
    listen 80 default_server;
    server_name 118.178.242.26 _;

    # Pilot dashboard + legacy dashboard share one port
    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }

    # WebSocket upgrade for Yjs CRDT sync
    location /sync/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_read_timeout 86400;
    }

    location /mcp/ {
        proxy_pass http://127.0.0.1:8767/;
    }

    location /artifacts/ {
        proxy_pass http://127.0.0.1:8001/artifacts/;
    }
}
NGINX

# Disable the old v1 conf if it conflicts
rm -f /etc/nginx/sites-enabled/flowguard_v4 2>/dev/null || true
nginx -t && systemctl reload nginx
echo '[ok] nginx reloaded'
EOF
)

if command -v sshpass >/dev/null; then
    sshpass -p "$PW" ssh -o StrictHostKeyChecking=no "$USER@$HOST" "$REMOTE_NGINX"
else
    ssh -o StrictHostKeyChecking=no "$USER@$HOST" "$REMOTE_NGINX"
fi

step "5/6 External smoke test"
curl -sf "http://$HOST/health" >/dev/null && echo "[ok] http://$HOST/health"
curl -sf "http://$HOST/api/pilot/scenarios" >/dev/null && echo "[ok] /api/pilot/scenarios"
curl -sf "http://$HOST/sync/health" >/dev/null && echo "[ok] /sync/health"

step "6/6 Done"
echo ""
echo "🎉 LarkMentor v2 is live:"
echo "  Pilot Dashboard: http://$HOST/dashboard/pilot"
echo "  Sync WebSocket:  ws://$HOST/sync/ws"
echo "  MCP API:         http://$HOST/mcp/tools"
echo ""
echo "Watch logs:  ssh $USER@$HOST 'journalctl -u larkmentor-v2-dashboard -f'"
