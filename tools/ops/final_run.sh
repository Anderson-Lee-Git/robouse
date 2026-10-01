#!/bin/bash
# Final v1 evaluation, one stream per model + harness pair, suites run one after another (one trial per task).
#   tools/ops/final_run.sh                     all suites below
#   tools/ops/final_run.sh metaworld libero    only these
# Jobs: runs/final-<suite>-<pair>/. Uses --resume, so rerunning continues where a stream stopped.
# Opus 5.5 is paused by the owner (2026-09-27); add "claude-code:claude-opus-5-5:3:opus" back to PAIRS to include it.
set -uo pipefail
cd "$(dirname "$0")/../.."
export MUJOCO_GL=cgl
# harness:model:concurrency:tag. Models other than a harness's own vendor's go through the trial's model gateway, which
# needs their provider key (e.g. BASETEN_API_KEY) in the environment and stops a trial at ROBOUSE_SPEND_CAP_USD (default 5).
PAIRS=("codex:gpt-6-astra:4:astra" "claude-code:baseten/zai-org/GLM-5.3:3:cc-glm" "codex:baseten/zai-org/GLM-5.3:2:codex-glm"
  "mini-swe-agent:baseten/zai-org/GLM-5.3:2:mini-glm")
if [ -n "${FINAL_PAIRS:-}" ]; then read -r -a PAIRS <<< "$FINAL_PAIRS"; fi
# Embodiment suites (not arms): quadruped humanoid mobile-manip dexhand crazyflie (robot models: `robouse fetch-assets`);
# driving needs MetaDrive in its own venv (docs/suites/driving.md).
SUITES=("$@"); [ ${#SUITES[@]} -gt 0 ] || SUITES=(metaworld gymrobotics libero libero-style arc-style robo-use-families safety vision hard
  crazyflie quadruped humanoid mobile-manip dexhand driving)
for spec in "${PAIRS[@]}"; do
  IFS=: read h m c tag <<< "$spec"
  (
    for suite in "${SUITES[@]}"; do
      [ -d "tasks/$suite" ] || continue
      job="runs/final-$suite-$tag"; mkdir -p "$job"
      .venv/bin/robouse run-many --tasks "tasks/$suite" --harness "$h" --model "$m" --out "$job" --concurrency "$c" --resume >> "$job/console.log" 2>&1
    done
  ) > "runs/_final-stream-$tag.log" 2>&1 &
done
echo "launched ${#PAIRS[@]} streams over: ${SUITES[*]}"
