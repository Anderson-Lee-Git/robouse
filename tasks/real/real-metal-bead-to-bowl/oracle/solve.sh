#!/bin/bash
# Reference solution: a fixed sequence of the task's skills, sent through the episode socket like an agent.
set -euo pipefail
ROBOUSE_REAL_ORACLE='[["grip", 60], ["move_to", 0.3, -0.15, 0.06], ["move_to", 0.3, -0.15, 0.005, 0.4], ["grip", 4], ["move_to", 0.3, -0.15, 0.08, 0.5], ["move_to", 0.42, -0.13, 0.12, 0.6], ["grip", 60]]' python -m robouse.oracle --backend real --env real-metal-bead-to-bowl
