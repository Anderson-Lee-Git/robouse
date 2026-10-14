#!/bin/bash
# Final v1 evaluation, one stream per model + harness pair, suites run one after another (one trial per task).
#   tools/ops/final_run.sh                     all suites below
#   tools/ops/final_run.sh metaworld libero    only these
# Jobs: runs/final-<suite>-<pair>/. Uses --resume, so rerunning continues where a stream stopped.
# Claude Opus 5.5 is not in PAIRS (paused since 2026-09-27); add "claude-code:claude-opus-5-5:3:opus" to include it.
set -uo pipefail
cd "$(dirname "$0")/../.."
export MUJOCO_GL=cgl
# harness:model:concurrency:tag. Models other than a harness's own vendor's go through the trial's model gateway, which
# needs their provider's settings in the environment: for glm/glm-5.3 (GLM-5.3 on the Z.ai Coding Plan) GLM_API_KEY and
# GLM_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4. The plan has no per-token price, so a glm/ stream runs
# without the spend cap (ROBOUSE_SPEND_CAP_USD=0 in that stream only, unless given); every other stream keeps the
# runner's default cap. Codex has no route to the plan (no Responses API).
# The tags differ from the September runs' (cc-glm, codex-glm, mini-glm, served by Baseten), so --resume never mixes the two.
PAIRS=("codex:gpt-6-astra:4:astra" "claude-code:glm/glm-5.3:3:cc-zai" "mini-swe-agent:glm/glm-5.3:2:mini-zai")
if [ -n "${FINAL_PAIRS:-}" ]; then read -r -a PAIRS <<< "$FINAL_PAIRS"; fi
# Embodiment suites (not arms): quadruped humanoid mobile-manip dexhand crazyflie (robot models: `robouse fetch-assets`);
# driving needs MetaDrive in its own venv (docs/suites/driving.md).
SUITES=("$@"); [ ${#SUITES[@]} -gt 0 ] || SUITES=(metaworld gymrobotics libero libero-style arc-style robo-use-families safety vision hard
  crazyflie quadruped humanoid mobile-manip dexhand driving)
for spec in "${PAIRS[@]}"; do
  IFS=: read h m c tag <<< "$spec"
  (
    if [ -z "${ROBOUSE_SPEND_CAP_USD:-}" ] && [[ $m == glm/* ]]; then export ROBOUSE_SPEND_CAP_USD=0; fi
    for suite in "${SUITES[@]}"; do
      [ -d "tasks/$suite" ] || continue
      job="runs/final-$suite-$tag"; mkdir -p "$job"
      .venv/bin/robouse run-many --tasks "tasks/$suite" --harness "$h" --model "$m" --out "$job" --concurrency "$c" --resume >> "$job/console.log" 2>&1
    done
  ) > "runs/_final-stream-$tag.log" 2>&1 &
done
echo "launched ${#PAIRS[@]} streams over: ${SUITES[*]}"
