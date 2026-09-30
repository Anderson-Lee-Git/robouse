#!/bin/bash
# Reference solution: a fixed sequence of the task's skills, sent through the episode socket like an agent.
set -euo pipefail
ROBOUSE_REAL_ORACLE='[["move_to", 0.2, 0.05, 0.08]]' python -m robouse.oracle --backend real --env real-so101-reach
