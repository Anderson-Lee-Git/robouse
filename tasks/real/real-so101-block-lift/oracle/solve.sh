#!/bin/bash
# Reference solution: a fixed sequence of the task's skills, sent through the episode socket like an agent.
set -euo pipefail
ROBOUSE_REAL_ORACLE='[["grip", 60], ["move_to", 0.22, -0.05, 0.08], ["move_to", 0.22, -0.05, 0.02, 0.4], ["grip", 2], ["move_to", 0.22, -0.05, 0.08, 0.5]]' python -m robouse.oracle --backend real --env real-so101-block-lift
