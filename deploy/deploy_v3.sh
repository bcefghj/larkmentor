#!/usr/bin/env bash
# LarkMentor v3 (Agent-Pilot + Harness) 一键蓝绿部署脚本
#
# 核心想法：
#   1. 服务器上维护两套目录：  /opt/lm_blue 与 /opt/lm_green
#   2. 当前生效的那一套由 /opt/lm_current 符号链接指向
#   3. 本次发布：上传到「待机」那一套 → 启新端口 systemd → smoke → 切流 → 停老
#   4. 任何一步失败，都保留旧版运行；rollback.sh 只是翻转符号链接再 reload
#
# 需要的环境变量：
#   HOST=阿里云公网 IP
#   REMOTE_USER=root        （默认 root）
#   REMOTE_PW=xxxxx         （不想传密码就配 ssh-key）

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
HOST="${HOST:-118.178.242.26}"
REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_PW="${REMOTE_PW:-bcefghj@Github666}"
SYMLINK=/opt/lm_current
BLUE=/opt/lm_blue
GREEN=/opt/lm_green

step() { printf "\n\033[1;36m== %s ==\033[0m\n" "$*"; }

ssh_run() {
  if command -v sshpass >/dev/null; then
    sshpass -p "$REMOTE_PW" ssh -o StrictHostKeyChecking=no "$REMOTE_USER@$HOST" "$@"
  else
    ssh "$REMOTE_USER@$HOST" "$@"
  fi
}
scp_to() {
  if command -v sshpass >/dev/null; then
    sshpass -p "$REMOTE_PW" scp -o StrictHostKeyChecking=no "$1" "$REMOTE_USER@$HOST:$2"
  else
    scp "$1" "$REMOTE_USER@$HOST:$2"
  fi
}

step "1. Local smoke"
(cd "$ROOT" && python -c "from dashboard.server import app; print('ok routes=', len(app.routes))")
(cd "$ROOT" && python -c "from core.agent_pilot.harness import default_orchestrator; default_orchestrator()")

step "2. Resolve the idle slot"
ACTIVE=$(ssh_run "readlink -f $SYMLINK 2>/dev/null || echo none")
if [[ "$ACTIVE" == "$BLUE" ]]; then IDLE=$GREEN; PORT=8011; else IDLE=$BLUE; PORT=8010; fi
echo "Active: $ACTIVE | deploying into: $IDLE (health port $PORT)"

step "3. Package"
TAR=/tmp/larkmentor_v3_$(date +%s).tar.gz
tar --exclude=.venv --exclude=__pycache__ --exclude=data/pilot_plans \
    --exclude=data/pilot_artifacts --exclude=.env --exclude=node_modules \
    -czf "$TAR" -C "$ROOT" .

step "4. Upload"
scp_to "$TAR" "/opt/$(basename $TAR)"

step "5. Unpack into idle slot + env + deps"
ssh_run "mkdir -p $IDLE && rm -rf $IDLE/* && tar -xzf /opt/$(basename $TAR) -C $IDLE"
ssh_run "[ -f $ACTIVE/.env ] && cp $ACTIVE/.env $IDLE/.env || true"
ssh_run "cd $IDLE && python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -r requirements.txt --quiet"

step "6. Start warm uvicorn on port $PORT for smoke"
ssh_run "cd $IDLE && nohup .venv/bin/uvicorn dashboard.server:app --host 0.0.0.0 --port $PORT > /tmp/lm_warm_$PORT.log 2>&1 & sleep 4; curl -fsS http://127.0.0.1:$PORT/api/pilot/context | head -c 200 || (cat /tmp/lm_warm_$PORT.log; exit 1)"

step "7. Flip symlink + systemd reload"
ssh_run "ln -snf $IDLE $SYMLINK && systemctl restart larkmentor larkmentor-dashboard 2>/dev/null || true"
ssh_run "pkill -f 'uvicorn dashboard.server:app --port $PORT' || true"

step "8. Post-flip smoke"
ssh_run "sleep 2; curl -fsS http://127.0.0.1:8001/api/pilot/context | head -c 200"

step "9. Record blue/green state"
ssh_run "echo 'active=$IDLE $(date -Iseconds)' > /opt/lm_last_deploy.txt"

echo "Deployed into $IDLE (previous: $ACTIVE). Roll back with deploy/rollback.sh"
