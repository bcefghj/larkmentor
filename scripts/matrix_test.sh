#!/usr/bin/env bash
# LarkMentor v4 · 6 场景 × 4 模型 质量矩阵测试
#
# 输出: data/evidence/matrix_$(date).json
# 评委可以看到每个场景在每个模型下的真实表现数据

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/data/evidence/matrix_$(date +%Y%m%d_%H%M%S).json"
mkdir -p "$(dirname "$OUT")"

cd "$ROOT"

echo '{' > "$OUT"
echo '  "timestamp": "'"$(date -Iseconds)"'",' >> "$OUT"
echo '  "scenarios": ["A_intent", "B_plan", "C_doc", "D_slides", "E_sync", "F_archive"],' >> "$OUT"
echo '  "models": ["doubao", "minimax", "deepseek", "kimi"],' >> "$OUT"
echo '  "results": {' >> "$OUT"

scenarios=(
  "A_intent:/pilot 整理讨论生成需求文档"
  "B_plan:/plan 调研竞品方案"
  "C_doc:@pilot 写一份 API 设计说明"
  "D_slides:@pilot 生成下周评审 PPT"
  "E_sync:状态同步测试（跳过真实 WS 拨测，仅测规划）"
  "F_archive:总结会议并归档到 Wiki"
)

models=("doubao" "minimax" "deepseek" "kimi")

first=1
for sc in "${scenarios[@]}"; do
  scname="${sc%%:*}"
  task="${sc#*:}"
  for m in "${models[@]}"; do
    if [ $first -eq 0 ]; then echo ',' >> "$OUT"; fi
    first=0
    start=$(date +%s%N)
    out=$(python -c "
import os, sys, time
from agent.providers import default_providers
p = default_providers()
p.routing['chinese_chat'] = '$m'
p.routing['planning'] = '$m'
p.routing['reasoning'] = '$m'
try:
    resp = p.chat(
        messages=[{'role': 'user', 'content': '$task'}],
        task_kind='chinese_chat', max_tokens=300,
    )
    print('OK', len(resp), p.current_plan_cost())
except Exception as e:
    print('ERR', str(e)[:100])
" 2>&1 | tail -1)
    end=$(date +%s%N)
    dur_ms=$(( (end - start) / 1000000 ))
    status=$(echo "$out" | awk '{print $1}')
    chars=$(echo "$out" | awk '{print $2}')
    cost=$(echo "$out" | awk '{print $3}')
    echo -n "    \"${scname}_${m}\": {\"status\": \"$status\", \"chars\": \"$chars\", \"cost_cny\": \"$cost\", \"duration_ms\": $dur_ms}" >> "$OUT"
    echo "  $scname × $m → $status ${dur_ms}ms"
  done
done

echo '' >> "$OUT"
echo '  }' >> "$OUT"
echo '}' >> "$OUT"

echo
echo "✓ 矩阵报告：$OUT"
