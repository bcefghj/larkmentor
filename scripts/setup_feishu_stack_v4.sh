#!/usr/bin/env bash
# LarkMentor v4 · 飞书官方栈一键安装
# 
# 安装：
# 1. @larksuite/cli（lark-cli 二进制 + 22 Skills）
# 2. @larksuiteoapi/lark-mcp 通过 npx 运行时加载（不持久安装，减少磁盘占用）
# 3. 验证 FEISHU_APP_ID / FEISHU_APP_SECRET 已配置
# 4. 生成 .larkmentor/mcp.json

set -euo pipefail

echo "═══════════════════════════════════════════════════"
echo "  LarkMentor v4 · 飞书官方栈安装"
echo "═══════════════════════════════════════════════════"

if ! command -v npm >/dev/null 2>&1; then
  echo "❌ npm 未安装，请先装 Node.js >= 18"
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 1. lark-cli
if ! command -v lark-cli >/dev/null 2>&1; then
  echo "==> 1/3 安装 @larksuite/cli"
  npm install -g @larksuite/cli || echo "⚠️ 全局安装失败，尝试 npx 运行"
else
  echo "✓ lark-cli 已安装：$(lark-cli --version 2>/dev/null || echo '?')"
fi

# 2. 22 Skills
echo "==> 2/3 安装 22 官方 Skills"
npx skills add larksuite/cli -y -g 2>&1 | tail -5 || echo "⚠️ skills 安装部分失败"

SKILLS_DIR="$HOME/.claude/skills"
if [ -d "$SKILLS_DIR" ]; then
  COUNT=$(ls "$SKILLS_DIR" 2>/dev/null | grep -c "^lark-" || true)
  echo "✓ $COUNT 个 lark-* Skills 已安装到 $SKILLS_DIR"
fi

# 3. MCP config
echo "==> 3/3 生成 .larkmentor/mcp.json"
MCP_CFG="$ROOT/.larkmentor/mcp.json"
mkdir -p "$(dirname "$MCP_CFG")"
cat > "$MCP_CFG" <<'JSON'
{
  "servers": [
    {
      "alias": "lark-local",
      "transport": "stdio",
      "command": "npx",
      "args": [
        "-y", "@larksuiteoapi/lark-mcp", "mcp",
        "-a", "${FEISHU_APP_ID}",
        "-s", "${FEISHU_APP_SECRET}",
        "-t", "preset.default,preset.im.default,preset.doc.default,preset.calendar.default,preset.base.default,preset.task.default"
      ],
      "env_pass": ["FEISHU_APP_ID", "FEISHU_APP_SECRET"],
      "enabled": true
    },
    {
      "alias": "lark-remote",
      "transport": "http",
      "url": "https://mcp.feishu.cn/mcp",
      "headers": {"Authorization": "Bearer ${FEISHU_MCP_TAT}"},
      "env_pass": ["FEISHU_MCP_TAT"],
      "enabled": false
    }
  ]
}
JSON
echo "✓ MCP 配置写入 $MCP_CFG"

# 4. Sanity checks
echo
echo "═══ Env sanity check ═══"
for v in FEISHU_APP_ID FEISHU_APP_SECRET; do
  if [ -z "${!v:-}" ]; then
    echo "⚠️ $v 未设置（MCP stdio 无法启动飞书 API）"
  else
    echo "✓ $v = ***"
  fi
done
for v in DOUBAO_API_KEY MINIMAX_API_KEY DEEPSEEK_API_KEY KIMI_API_KEY; do
  if [ -z "${!v:-}" ]; then
    echo "⚠️ $v 未设置"
  else
    echo "✓ $v = ***"
  fi
done

echo
echo "✓ 安装完成。运行测试：python -m agent mcp"
