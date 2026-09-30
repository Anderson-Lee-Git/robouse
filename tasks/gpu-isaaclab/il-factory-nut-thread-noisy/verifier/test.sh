#!/bin/bash
# Verifier: the episode server already judged success (the simulator's own physical success check, evaluated by the
# GPU worker after `robo done` and a settle period); copy its verdict.
set -euo pipefail
OUT="${ROBOUSE_VERIFIER_DIR:-/logs/verifier}"
mkdir -p "$OUT"
python3 - "$ROBOUSE_EPISODE_DIR/result.json" "$OUT/reward.txt" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
open(sys.argv[2], "w").write("1" if r.get("success") else "0")
print("success" if r.get("success") else "fail", r.get("outcome"))
EOF
