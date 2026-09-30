#!/bin/bash
# Reference solution: the task's planner policy runs next to the simulator on the privileged state (oracle token) and
# hands its next action to this loop, which sends it through the robo socket like an agent's `robo act` / `robo skill`.
set -euo pipefail
python -m robouse.oracle --backend gpu --env go1-moving-gates
