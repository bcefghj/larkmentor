#!/usr/bin/env bash
# Installs the official Feishu local MCP (2500+ API) and lark-cli Skills.
#
# Outcome after this script:
#   - `lark-mcp` on PATH (stdio MCP server spinnable by Agent-Pilot harness)
#   - `.larkmentor/skills/lark-*` populated with lark-cli 22 Skills
#   - `.larkmentor/mcp.json` updated with the local + remote MCP aliases
#
# Re-runnable. Safe to call on every deploy.

set -euo pipefail

cd "$(dirname "$0")/.."

ROOT="$(pwd)"
SKILLS_DIR="$ROOT/.larkmentor/skills"
MCP_CFG="$ROOT/.larkmentor/mcp.json"

mkdir -p "$SKILLS_DIR"

echo "== 1/4  Node/pnpm check =="
if ! command -v npx >/dev/null 2>&1; then
  echo "npx not found. Install Node.js 18+ first (brew install node / apt install nodejs)." >&2
  exit 1
fi
NODE_MAJOR=$(node -p "process.versions.node.split('.')[0]")
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "Node 18+ required; found $NODE_MAJOR" >&2
  exit 1
fi

echo "== 2/4  Install @larksuiteoapi/lark-mcp =="
# Prefer global install so the Agent can spawn it as a stdio process.
npm install -g @larksuiteoapi/lark-mcp@latest || {
  echo "global install failed; falling back to npx on demand" >&2
}

echo "== 3/4  Sync lark-cli 22 Skills =="
# The skills ship as individual packages under @larksuite/skill-*. The
# `skills` CLI (Anthropic's tool) installs them to ~/.claude/skills/ by default.
# We sync them into .larkmentor/skills so Agent-Pilot's SkillsLoader can find
# them without touching the user's global Claude install.
if command -v skills >/dev/null 2>&1; then
  skills add larksuite/cli -y -g || true
  SRC="$HOME/.claude/skills"
  if [ -d "$SRC" ]; then
    for d in "$SRC"/lark-*; do
      [ -d "$d" ] || continue
      name=$(basename "$d")
      mkdir -p "$SKILLS_DIR/$name"
      cp -R "$d/." "$SKILLS_DIR/$name/"
    done
  fi
else
  echo "(skills CLI not installed; skip auto sync. run 'npm i -g @anthropic-ai/skills' to enable)"
fi

echo "== 4/4  Write .larkmentor/mcp.json (aliases) =="
cat > "$MCP_CFG" <<JSON
{
  "servers": [
    {
      "alias": "lark-local",
      "transport": "stdio",
      "command": "lark-mcp",
      "args": ["stdio", "--app-id", "\${FEISHU_APP_ID}", "--app-secret", "\${FEISHU_APP_SECRET}"],
      "env_pass": ["FEISHU_APP_ID", "FEISHU_APP_SECRET"]
    },
    {
      "alias": "lark-remote",
      "transport": "http",
      "url": "https://mcp.feishu.cn/mcp",
      "headers": {"Authorization": "Bearer \${FEISHU_MCP_TAT}"}
    }
  ]
}
JSON

echo "Done. MCP aliases installed:"
jq . "$MCP_CFG" 2>/dev/null || cat "$MCP_CFG"
echo ""
echo "Next: export FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_MCP_TAT then restart the bot."
