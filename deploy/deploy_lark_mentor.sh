#!/usr/bin/env bash
# LarkMentor v1 部署脚本（冷切换 v4 → LarkMentor）
#
# 1. 本地 pytest 必须全过
# 2. 打 tar 包 → scp 上传 /opt/larkmentor_release.tar.gz
# 3. 远端：
#    a) 备份 v4 数据到 /root/v4_backup_<ts>/
#    b) 解压到 /opt/larkmentor/，复制 v4 .env + user_states.json + coach_kb.sqlite + growth_entries.jsonl
#    c) 装依赖
#    d) 写 systemd unit larkmentor.service / -mcp / -dashboard
#    e) 冷切换：停 v4 → 启 LarkMentor → smoke_test → 失败 rollback
#    f) nginx 路由保持（端口共用 8001 / 8767）

set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DEPLOY_DIR/.." && pwd)"
PROJ="$ROOT/40_code/project"
HOST="118.178.242.26"
REMOTE_BASE="/opt/larkmentor"
REMOTE_TAR="/opt/larkmentor_release.tar.gz"

SSH="$DEPLOY_DIR/_ssh_lib.exp"
SCP="$DEPLOY_DIR/_scp_lib.exp"
SCPGET="$DEPLOY_DIR/_scp_get.exp"

chmod +x "$SSH" "$SCP" "$SCPGET" "$0"

step() { printf "\n\033[1;36m== %s ==\033[0m\n" "$*"; }

step "0/6 本地 pytest 必须 100% 通过"
( cd "$PROJ" && PYTHONPATH=. python3 -m pytest tests/ -q \
    --ignore=tests/e2e --ignore=tests/simulator ) || {
    echo "[FAIL] pytest 失败，拒绝部署"
    exit 1
}

step "1/6 打包源码"
TARBALL="$ROOT/.larkmentor_release.tar.gz"
( cd "$ROOT/40_code" && COPYFILE_DISABLE=1 tar \
    --exclude='project/data' \
    --exclude='project/.venv' \
    --exclude='project/.env' \
    --exclude='**/__pycache__' \
    --exclude='**/.pytest_cache' \
    --exclude='**/*.pyc' \
    --exclude='**/.DS_Store' \
    -czf "$TARBALL" \
    project 2>/dev/null )
ls -lh "$TARBALL"

step "2/6 上传 tarball"
"$SCP" "$TARBALL" "$REMOTE_TAR"

step "3/6 远端：备份 v4 + 解压 + 装依赖 + 写 systemd"
"$SSH" "set -e
TS=\$(date +%Y%m%d_%H%M%S)

# 3a. 备份 v4 数据
BACKUP=/root/v4_backup_\$TS
mkdir -p \$BACKUP
if [ -d /opt/flowguard_v4/project/data ]; then
    cp -r /opt/flowguard_v4/project/data \$BACKUP/data
    echo \"[ok] backed up v4 data -> \$BACKUP/data\"
fi
cp /etc/systemd/system/flowguard-v4*.service \$BACKUP/ 2>/dev/null || true

# 3b. 解压
mkdir -p $REMOTE_BASE
cd $REMOTE_BASE
tar -xzf $REMOTE_TAR
echo '[ok] LarkMentor extracted'

# 3c. 复用 v4 .env + 持久化数据（向后兼容）
if [ -f /opt/flowguard_v4/project/.env ]; then
    cp /opt/flowguard_v4/project/.env project/.env
    echo '[ok] .env from v4'
fi
mkdir -p project/data
for f in user_states.json sender_profiles.json org_docs.json user_workspaces.json decision_log.json coach_kb.sqlite growth_entries.jsonl; do
    if [ -f /opt/flowguard_v4/project/data/\$f ]; then
        cp /opt/flowguard_v4/project/data/\$f project/data/
    fi
done
# 复制 audit / archival / working 目录
for d in audit archival working_memory flow_memory_md; do
    if [ -d /opt/flowguard_v4/project/data/\$d ]; then
        cp -r /opt/flowguard_v4/project/data/\$d project/data/
    fi
done

# 3d. Python venv + 依赖
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r project/requirements.txt
echo '[ok] python deps'

# 3e. systemd unit (复用 v4 端口 8001/8767)
cat > /etc/systemd/system/larkmentor.service <<'UNIT'
[Unit]
Description=LarkMentor (Smart Shield + Rookie Mentor)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/larkmentor/project
EnvironmentFile=-/opt/larkmentor/project/.env
ExecStart=/opt/larkmentor/.venv/bin/python -u main.py
Restart=always
RestartSec=5
StandardOutput=append:/var/log/larkmentor.log
StandardError=append:/var/log/larkmentor.err.log

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/larkmentor-dashboard.service <<'UNIT'
[Unit]
Description=LarkMentor Dashboard (FastAPI on 8001)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/larkmentor/project
EnvironmentFile=-/opt/larkmentor/project/.env
ExecStart=/opt/larkmentor/.venv/bin/uvicorn dashboard.server:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=5
StandardOutput=append:/var/log/larkmentor-dashboard.log
StandardError=append:/var/log/larkmentor-dashboard.err.log

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/larkmentor-mcp.service <<'UNIT'
[Unit]
Description=LarkMentor MCP HTTP (8767)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/larkmentor/project
EnvironmentFile=-/opt/larkmentor/project/.env
ExecStart=/opt/larkmentor/.venv/bin/python -m core.mcp_server.server --transport http --port 8767
Restart=always
RestartSec=5
StandardOutput=append:/var/log/larkmentor-mcp.log
StandardError=append:/var/log/larkmentor-mcp.err.log

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
echo '[ok] systemd units written'
"

step "4/6 冷切换：停 v4 → 启 LarkMentor"
"$SSH" "set +e
echo '[step] stopping v4 ...'
systemctl stop flowguard-v4.service flowguard-v4-mcp.service flowguard-v4-dashboard.service 2>/dev/null
sleep 2
echo '[step] disabling v4 (rollback 用 enable 重启)'
systemctl disable flowguard-v4.service flowguard-v4-mcp.service flowguard-v4-dashboard.service 2>/dev/null

echo '[step] starting LarkMentor ...'
systemctl enable larkmentor.service larkmentor-dashboard.service larkmentor-mcp.service >/dev/null 2>&1
systemctl start larkmentor-dashboard.service
systemctl start larkmentor-mcp.service
systemctl start larkmentor.service
sleep 6
systemctl is-active larkmentor.service larkmentor-dashboard.service larkmentor-mcp.service
"

step "5a/6 上传新版网站 bundle 到 /var/www/larkmentor/"
WEB_DIR="$ROOT/70_website/version-c-larkmentor"
WEB_TARBALL="$ROOT/.larkmentor_web.tar.gz"
( cd "$WEB_DIR" && COPYFILE_DISABLE=1 tar \
    --exclude='**/.DS_Store' \
    -czf "$WEB_TARBALL" . 2>/dev/null )
ls -lh "$WEB_TARBALL"
"$SCP" "$WEB_TARBALL" "/opt/larkmentor_web.tar.gz"

"$SSH" "set -e
mkdir -p /var/www/larkmentor.new
tar -xzf /opt/larkmentor_web.tar.gz -C /var/www/larkmentor.new
# atomic switch
rm -rf /var/www/larkmentor.bak 2>/dev/null
[ -d /var/www/larkmentor ] && mv /var/www/larkmentor /var/www/larkmentor.bak || true
mv /var/www/larkmentor.new /var/www/larkmentor
echo '[ok] web bundle live at /var/www/larkmentor'
"

step "5b/6 写入 nginx server (保留 /dashboard /mcp /api 反代，仅切换 root)"
"$SSH" "set -e
cat > /etc/nginx/sites-available/larkmentor <<'NGX'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    root /var/www/larkmentor;
    index index.html;

    # ---------- static homepage ----------
    location = / {
        try_files /index.html =404;
    }
    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # ---------- /dashboard -> FastAPI 8001/v3 ----------
    location = /dashboard      { proxy_pass http://127.0.0.1:8001/v3; }
    location  /dashboard/      { proxy_pass http://127.0.0.1:8001/; }
    location  /static/         { proxy_pass http://127.0.0.1:8001/static/; }

    # ---------- /api  -> FastAPI 8001 ----------
    location  /api/            {
        proxy_pass http://127.0.0.1:8001/api/;
        proxy_set_header Host \$host;
    }
    location = /health         { proxy_pass http://127.0.0.1:8001/health; }

    # ---------- /mcp  -> MCP server 8767 ----------
    location = /mcp            { proxy_pass http://127.0.0.1:8767/; }
    location = /mcp/           { proxy_pass http://127.0.0.1:8767/; }
    location  /mcp/            { proxy_pass http://127.0.0.1:8767/; }

    # ---------- common headers ----------
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection \"upgrade\";
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_read_timeout 60s;

    # ---------- gzip ----------
    gzip on;
    gzip_types text/plain text/css application/javascript application/json image/svg+xml;
    gzip_min_length 512;
}
NGX

# disable any prior default / flowguard / flowguard_v4 sites, enable larkmentor
rm -f /etc/nginx/sites-enabled/default 2>/dev/null
rm -f /etc/nginx/sites-enabled/flowguard 2>/dev/null
rm -f /etc/nginx/sites-enabled/flowguard_v3 2>/dev/null
rm -f /etc/nginx/sites-enabled/flowguard_v4 2>/dev/null
rm -f /etc/nginx/sites-enabled/larkmentor 2>/dev/null
ln -s /etc/nginx/sites-available/larkmentor /etc/nginx/sites-enabled/larkmentor

nginx -t && systemctl reload nginx
echo '[ok] nginx switched to larkmentor server'
"

step "6/6 smoke_test"
if bash "$DEPLOY_DIR/smoke_test.sh"; then
    echo
    echo "✅ LarkMentor v1 已部署且 smoke 全过"
    echo "   主页:       http://$HOST/"
    echo "   Dashboard:  http://$HOST/dashboard"
    echo "   MCP HTTP:   http://$HOST/mcp/tools"
    echo "   GitHub:     https://github.com/bcefghj/larkmentor"
else
    echo
    echo "❌ smoke_test 失败，自动回滚到 v4"
    bash "$DEPLOY_DIR/rollback.sh"
    exit 1
fi
