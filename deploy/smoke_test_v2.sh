#!/usr/bin/env bash
# Post-deploy smoke test for LarkMentor v2 (runs on the server).
# 20 checks covering Bot / Dashboard / Pilot / Sync / MCP.

set -e

BASE="${BASE:-http://127.0.0.1:8001}"
MCP="${MCP:-http://127.0.0.1:8767}"
FAIL=0

check() {
    local name="$1"; shift
    if "$@" >/dev/null 2>&1; then
        printf "[OK] %s\n" "$name"
    else
        printf "[FAIL] %s\n" "$name"
        FAIL=1
    fi
}

# ── FastAPI core ──
check "dashboard /health"            curl -sf "$BASE/health"
check "dashboard /api/overview"      curl -sf "$BASE/api/overview"
check "dashboard /api/decisions"     curl -sf "$BASE/api/decisions"

# ── Agent-Pilot ──
check "pilot /api/pilot/scenarios"   curl -sf "$BASE/api/pilot/scenarios"
check "pilot /api/pilot/plans"       curl -sf "$BASE/api/pilot/plans"

# Launch + follow
PLAN_JSON=$(curl -sf -X POST -H "Content-Type: application/json" \
    -d '{"intent":"smoke test plan","open_id":"ou_smoke"}' \
    "$BASE/api/pilot/launch" || echo '{}')
echo "$PLAN_JSON" | grep -q plan_id && printf "[OK] pilot launch\n" || { printf "[FAIL] pilot launch\n"; FAIL=1; }

PLAN_ID=$(echo "$PLAN_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin).get('plan_id',''))")
if [ -n "$PLAN_ID" ]; then
    sleep 1
    check "pilot /api/pilot/plan/$PLAN_ID"  curl -sf "$BASE/api/pilot/plan/$PLAN_ID"
    check "pilot recommend"                  curl -sf "$BASE/api/pilot/recommend/$PLAN_ID"
    check "pilot share page"                 curl -sf "$BASE/pilot/$PLAN_ID"
else
    FAIL=1
fi

# ── Clarify / advanced ──
check "pilot clarify"                curl -sf -X POST -H "Content-Type: application/json" \
    -d '{"intent":"帮我处理"}' "$BASE/api/pilot/clarify"

# ── Sync WebSocket hub ──
check "sync /sync/health"            curl -sf "$BASE/sync/health"
check "sync /sync/rooms"             curl -sf "$BASE/sync/rooms"

# ── MCP tools endpoint ──
check "mcp /tools"                   curl -sf "$MCP/tools"

# ── Artifacts static ──
mkdir -p "$(dirname "$0")/../data/pilot_artifacts"
echo "smoke_$(date +%s)" > "$(dirname "$0")/../data/pilot_artifacts/smoke.txt"
check "artifacts static"             curl -sf "$BASE/artifacts/smoke.txt"

# ── Dashboard Pilot HTML page ──
check "pilot dashboard page"         curl -sf "$BASE/dashboard/pilot"

if [ "$FAIL" -eq 0 ]; then
    echo ""
    echo "🎉 All 14+ smoke checks passed."
    exit 0
else
    echo ""
    echo "❌ Some smoke checks failed. See output above."
    exit 1
fi
