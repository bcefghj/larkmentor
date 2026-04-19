#!/usr/bin/env bash
# LarkMentor 部署后 15 项验证
set -uo pipefail

HOST="118.178.242.26"
DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
SSH="$DEPLOY_DIR/_ssh_lib.exp"

PASS=0; FAIL=0; TOTAL=0

check_http() {
    local label="$1"; local url="$2"; local expected="$3"
    TOTAL=$((TOTAL+1))
    local code
    code=$(curl -sS -o /dev/null -w "%{http_code}" -m 10 "$url" || echo "000")
    if [ "$code" = "$expected" ]; then
        printf "  ✅ [%03d] %s\n" "$code" "$label"; PASS=$((PASS+1))
    else
        printf "  ❌ [%03d] %s (expected %s)\n" "$code" "$label" "$expected"; FAIL=$((FAIL+1))
    fi
}

check_contains() {
    local label="$1"; local url="$2"; local needle="$3"
    TOTAL=$((TOTAL+1))
    local body
    body=$(curl -sS --compressed -m 10 "$url" 2>/dev/null || echo "")
    if echo "$body" | grep -q "$needle"; then
        printf "  ✅ %s contains '%s'\n" "$label" "$needle"; PASS=$((PASS+1))
    else
        printf "  ❌ %s missing '%s'\n" "$label" "$needle"; FAIL=$((FAIL+1))
    fi
}

check_systemd() {
    local svc="$1"
    TOTAL=$((TOTAL+1))
    local status
    status=$("$SSH" "systemctl is-active $svc" 2>&1 | tail -1 | tr -d '\r')
    if [ "$status" = "active" ]; then
        printf "  ✅ systemd %s = active\n" "$svc"; PASS=$((PASS+1))
    else
        printf "  ❌ systemd %s = %s\n" "$svc" "$status"; FAIL=$((FAIL+1))
    fi
}

echo "── LarkMentor smoke_test ──"

check_systemd "larkmentor.service"
check_systemd "larkmentor-dashboard.service"
check_systemd "larkmentor-mcp.service"

check_http "主页"           "http://$HOST/"            "200"
check_http "Dashboard"      "http://$HOST/dashboard"   "200"
check_http "Health"         "http://$HOST/health"      "200"
check_http "MCP tools"      "http://$HOST/mcp/tools"   "200"

check_contains "Health body"           "http://$HOST/health"     "ok"
check_contains "MCP mentor_review"     "http://$HOST/mcp/tools"  "mentor_review_message"
check_contains "MCP mentor_clarify"    "http://$HOST/mcp/tools"  "mentor_clarify_task"
check_contains "MCP mentor_draft"      "http://$HOST/mcp/tools"  "mentor_draft_weekly"
check_contains "MCP mentor_kb"         "http://$HOST/mcp/tools"  "mentor_search_org_kb"
check_contains "MCP coach_review alias" "http://$HOST/mcp/tools" "coach_review_message"
check_contains "MCP get_focus_status (v3)" "http://$HOST/mcp/tools" "get_focus_status"

# new v-c assertions
check_http     "MCP visual page"      "http://$HOST/mcp"            "200"
check_http     "MCP tools.json alias" "http://$HOST/mcp/tools.json" "200"
check_contains "Homepage is LarkMentor v-c"   "http://$HOST/"          "LarkMentor"
check_contains "Homepage hero copy"           "http://$HOST/"          "守护注意力"
check_contains "Dashboard is v-c new"         "http://$HOST/dashboard" "lm-dashboard-version"
check_contains "MCP visual is v-c new"        "http://$HOST/mcp"       "lm-mcp-version"
check_contains "MCP tools.json carries tools" "http://$HOST/mcp/tools.json" "mentor_review_message"

# 15 recent log no ERROR
TOTAL=$((TOTAL+1))
err=$("$SSH" "tail -n 30 /var/log/larkmentor.log 2>/dev/null | grep -c ERROR || true" 2>&1 | tail -1 | tr -d '\r')
if [ "${err:-0}" = "0" ]; then
    printf "  ✅ recent log no ERROR\n"; PASS=$((PASS+1))
else
    printf "  ❌ recent log %s ERROR lines\n" "$err"; FAIL=$((FAIL+1))
fi

echo
echo "── result: $PASS/$TOTAL passed ──"
[ "$FAIL" -gt 0 ] && exit 1 || exit 0
