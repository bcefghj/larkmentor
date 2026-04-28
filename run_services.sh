#!/usr/bin/env bash
# Launch all 3 LarkMentor v2 services in background.
# In production systemd replaces this; this script is for local dev.

set -e
cd "$(dirname "$0")"

export PYTHONPATH="$(pwd):$PYTHONPATH"
mkdir -p logs

echo "[1/3] Starting Feishu Bot (main.py) ..."
nohup python main.py >> logs/bot.log 2>&1 &
echo "    PID=$!"

echo "[2/3] Starting Dashboard + Sync WebSocket (uvicorn :8001) ..."
nohup uvicorn dashboard.server:app --host 0.0.0.0 --port 8001 >> logs/dashboard.log 2>&1 &
echo "    PID=$!"

echo "[3/3] Starting MCP Server (HTTP :8767) ..."
nohup python -m core.mcp_server.server --transport http --port 8767 >> logs/mcp.log 2>&1 &
echo "    PID=$!"

sleep 2
echo ""
echo "Local endpoints:"
echo "  - Dashboard     http://localhost:8001/"
echo "  - Pilot UI      http://localhost:8001/dashboard/pilot"
echo "  - Sync WS       ws://localhost:8001/sync/ws"
echo "  - Pilot API     http://localhost:8001/api/pilot/plans"
echo "  - MCP HTTP      http://localhost:8767/"
echo ""
echo "Tail logs with:  tail -f logs/*.log"
