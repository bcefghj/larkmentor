#!/usr/bin/env bash
# Reset the offline-merge demo state to a clean baseline.
# Run before recording the 30s demo described in docs/DEMO_OFFLINE_30s.md.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ROOMS=("canvas:demo-offline" "doc:demo-offline")

echo "== 1/3  Clear CRDT hub rooms =="
for r in "${ROOMS[@]}"; do
  curl -sS -X DELETE "http://localhost:8000/sync/rooms/$r" || true
done

echo "== 2/3  Purge local artifacts =="
rm -f data/pilot_artifacts/*demo-offline*.json || true

echo "== 3/3  Seed baseline shapes =="
python - <<'PY'
import json, os
os.makedirs("data/pilot_artifacts", exist_ok=True)
baseline = {"title": "Demo Offline", "version": 0, "shapes": []}
with open("data/pilot_artifacts/demo-offline.json", "w") as fh:
    json.dump(baseline, fh)
print("baseline written")
PY

echo "Done. Both rooms empty; start the demo."
