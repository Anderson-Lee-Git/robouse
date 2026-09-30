#!/bin/bash
# Reference solution: a fixed sequence of the task's skills, sent through the episode socket like an agent.
set -euo pipefail
ROBOUSE_REAL_ORACLE='[["move_joints", 20, 40, -50, 0, 20, 0]]' python -m robouse.oracle --backend real --env real-piper-joint-pose
