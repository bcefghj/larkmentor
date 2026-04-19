#!/usr/bin/env bash
# 一键回滚：LarkMentor → v4
set -uo pipefail
HOST="118.178.242.26"
DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
SSH="$DEPLOY_DIR/_ssh_lib.exp"

step() { printf "\n\033[1;31m== ROLLBACK · %s ==\033[0m\n" "$*"; }

step "1/2 停 LarkMentor，启 v4"
"$SSH" "set +e
systemctl stop larkmentor.service larkmentor-dashboard.service larkmentor-mcp.service 2>/dev/null
systemctl enable flowguard-v4.service flowguard-v4-dashboard.service flowguard-v4-mcp.service 2>/dev/null
systemctl start flowguard-v4-dashboard.service flowguard-v4-mcp.service flowguard-v4.service
sleep 4
systemctl is-active flowguard-v4.service flowguard-v4-dashboard.service flowguard-v4-mcp.service
"

step "2/2 健康检查"
sleep 2
code=$(curl -sS -o /dev/null -w '%{http_code}' -m 10 "http://$HOST/health" || echo 000)
echo "  v4 /health -> $code"

echo
echo "✅ rollback to v4 完成。"
