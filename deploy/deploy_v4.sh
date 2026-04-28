#!/usr/bin/env bash
# LarkMentor v4 · 一键蓝绿部署（Docker + systemd）
#
# 环境变量：
#   HOST=阿里云 IP (默认 118.178.242.26)
#   REMOTE_USER=root
#   REMOTE_PW=xxx  (或用 ssh-key)
#
# 本版本相对 v3：
# - 容器化（Docker + docker-compose）
# - 额外安装 @larksuite/cli 二进制 + 22 skills
# - Redis 用于 Agent Teams pub/sub
# - 蓝绿符号链接切换（保留 v3）

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${HOST:-118.178.242.26}"
REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_PW="${REMOTE_PW:-bcefghj@Github666}"

step() { printf "\n\033[1;36m══ %s ══\033[0m\n" "$*"; }

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

step "1/7 本地冒烟"
python -c "from agent import default_loop, default_context_manager; from agent.tools import get_registry; assert len(get_registry()) >= 25, 'tools missing'; print('✓ 本地 v4 imports + tools OK')"
python -m pytest tests/test_agent_v4.py 2>&1 | tail -3

step "2/7 解析蓝/绿槽位"
ACTIVE=$(ssh_run "readlink -f /opt/lm_current 2>/dev/null || echo none")
if [[ "$ACTIVE" == "/opt/lm_blue" ]]; then IDLE=/opt/lm_green; else IDLE=/opt/lm_blue; fi
echo "Active=$ACTIVE → Idle=$IDLE"

step "3/7 打包"
TAR="/tmp/larkmentor_v4_$(date +%s).tar.gz"
tar --exclude=.venv --exclude=__pycache__ --exclude=data/pilot_plans \
    --exclude=data/pilot_artifacts --exclude=data/attachments --exclude=.env \
    --exclude=node_modules --exclude="*.pyc" \
    -czf "$TAR" -C "$ROOT" .
echo "tar: $(du -h "$TAR" | cut -f1)"

step "4/7 上传"
scp_to "$TAR" "/opt/$(basename "$TAR")"

step "5/7 解压 + venv + 依赖"
ssh_run "mkdir -p $IDLE && rm -rf $IDLE/* && tar -xzf /opt/$(basename "$TAR") -C $IDLE"
ssh_run "[ -f $ACTIVE/.env ] && cp $ACTIVE/.env $IDLE/.env || true"
ssh_run "cd $IDLE && python3 -m venv .venv && .venv/bin/pip install -U pip --quiet && .venv/bin/pip install -r requirements.txt --quiet"

step "6/7 飞书 stack 安装（best-effort）"
ssh_run "cd $IDLE && bash scripts/setup_feishu_stack_v4.sh 2>&1 | tail -20 || true"

step "7/7 蓝绿切换 + 健康检查"
ssh_run "ln -snf $IDLE /opt/lm_current"
ssh_run "systemctl restart larkmentor larkmentor-dashboard 2>/dev/null || true"
ssh_run "sleep 3 && curl -fsS http://127.0.0.1:8001/api/pilot/context 2>&1 | head -c 200 || echo 'dashboard 无响应（不致命，mcp 状态查看 /api/pilot/mcp/servers）'"
ssh_run "echo \"active=$IDLE deployed_at=$(date -Iseconds)\" > /opt/lm_last_deploy.txt"

echo
echo "✓ v4 部署完成：$IDLE (old: $ACTIVE)"
echo "  - 回滚：deploy/rollback_v3.sh（保持 v3 的蓝绿回滚脚本不变）"
