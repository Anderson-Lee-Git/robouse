#!/bin/bash
# No scripted solution exists for these real-world tasks (upstream's scripted policy reads its mock's
# privileged state). This moves both arms home and opens the grippers, then ends the episode, which
# exercises the pipeline; success needs a policy and a real rig.
set -euo pipefail
ROBOUSE_REAL_ORACLE='[["home"], ["grip", 60, "both"]]' python -m robouse.oracle --backend real --env x
