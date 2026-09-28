#!/bin/bash
# Reference solution: a scripted sequence of BEHAVIOR symbolic primitives (plan.json), sent through the robo socket
# exactly like an agent's `robo skill` calls.
set -euo pipefail
ROBOUSE_BEHAVIOR_PLAN="$(dirname "$0")/plan.json" python -m robouse.oracle --backend behavior --env bringing_water
