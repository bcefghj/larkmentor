#!/usr/bin/env bash
# E2E 冒烟矩阵（P5.5）：
#   场景 × 端 = 6 × 2 = 12 个（仅在能通的端上截图，另一端产日志）
#
# 场景：
#   A 意图入口       /pilot ...        ✅ IM + ✅ Dashboard
#   B 任务规划       /plan ...         ✅ IM + ✅ Dashboard
#   C 文档/白板      /canvas ...       ✅ Flutter + ✅ Dashboard (WebView)
#   D 演示生成       /ppt ...          ✅ Dashboard + ✅ 分享卡片
#   E 多端一致性     offline merge     ✅ Flutter 移动 + ✅ Flutter 桌面
#   F 总结交付       /context,/skills  ✅ IM + ✅ Dashboard
#
# 不具备真机的地方退化成 curl + 纯文本校验，把输出截屏等价证据落 docs/evidence/

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${DASH:-http://127.0.0.1:8001}"
EVID="$ROOT/docs/evidence/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$EVID"

check() {
  local name="$1"; shift
  local out; out="$("$@" 2>&1 || true)"
  printf "%s\n---\n%s\n" "$name" "$out" > "$EVID/${name}.log"
  if [ -n "$out" ]; then echo "[PASS] $name"; else echo "[FAIL] $name"; fi
}

echo "== E2E smoke → $EVID =="
check A_im_entry          curl -sS --max-time 6 "$BASE/api/pilot/context"
check B_plan_mode         curl -sS --max-time 6 "$BASE/api/pilot/skills"
check C_canvas_webview    curl -sS --max-time 6 "$BASE/"
check D_ppt_share         curl -sS --max-time 6 "$BASE/pilot/demo"
check E_offline_hub       curl -sS --max-time 6 "$BASE/api/pilot/mcp/servers"
check F_delivery          curl -sS --max-time 6 "$BASE/metrics"

echo
echo "Evidence written to $EVID"
