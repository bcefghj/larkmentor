#!/usr/bin/env bash
# v4 web_bundle 构建脚本
# Usage: bash build.sh
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v npm >/dev/null 2>&1; then
  echo "❌ npm not found. Install Node.js first (>= 18)."
  exit 1
fi

echo "== Installing deps (yjs + tldraw + tiptap + vite) =="
npm install --silent

echo "== Building (vite build) =="
npm run build

echo "== Done. Artifacts in ./dist/ =="
ls -la dist/
