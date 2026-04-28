#!/usr/bin/env bash
# v3 蓝绿回滚：把 /opt/lm_current 翻回另一套目录，然后重启 systemd。
# 保留 rollback.sh 作为 v4 紧急回滚入口，两者不互斥。

set -euo pipefail
HOST="${HOST:-118.178.242.26}"
REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_PW="${REMOTE_PW:-bcefghj@Github666}"

ssh_run() {
  if command -v sshpass >/dev/null; then
    sshpass -p "$REMOTE_PW" ssh -o StrictHostKeyChecking=no "$REMOTE_USER@$HOST" "$@"
  else
    ssh "$REMOTE_USER@$HOST" "$@"
  fi
}

echo "== v3 Blue/Green rollback =="
CUR=$(ssh_run "readlink -f /opt/lm_current 2>/dev/null || echo none")
if [[ "$CUR" == "/opt/lm_blue" ]]; then TARGET=/opt/lm_green; else TARGET=/opt/lm_blue; fi
echo "Current: $CUR  -->  Target: $TARGET"

ssh_run "[ -d $TARGET ] || { echo 'target slot missing — no rollback candidate'; exit 1; }"
ssh_run "ln -snf $TARGET /opt/lm_current && systemctl restart larkmentor larkmentor-dashboard 2>/dev/null || true"
ssh_run "sleep 2; curl -fsS http://127.0.0.1:8001/api/pilot/context | head -c 200 || true"
echo "Rolled back to $TARGET"
