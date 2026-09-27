#!/bin/bash
# Final v1 evaluation: every model + harness pair on the given suites (one trial per task).
#   scripts/final_run.sh metaworld gymrobotics
# Jobs: runs/final-<suite>-<pair>/. Safe to rerun: run-many starts fresh trial dirs; rerun_infra.py handles infra failures.
set -uo pipefail
cd "$(dirname "$0")/.."
PAIRS=("claude-code:claude-opus-5-5:4:opus" "codex:gpt-6-astra:4:astra" "claude-code-glm::3:cc-glm" "codex-glm::2:codex-glm" "mini-swe-agent-glm::2:mini-glm")
for suite in "$@"; do
  for spec in "${PAIRS[@]}"; do
    IFS=: read h m c tag <<< "$spec"
    job="runs/final-$suite-$tag"; mkdir -p "$job"
    nohup .venv/bin/robouse run-many --tasks "tasks/$suite" --harness "$h" --model "$m" --out "$job" --concurrency "$c" > "$job/console.log" 2>&1 &
  done
done
echo "launched $# suite(s) x ${#PAIRS[@]} pairs"
