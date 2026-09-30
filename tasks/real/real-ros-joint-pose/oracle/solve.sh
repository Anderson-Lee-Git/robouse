#!/bin/bash
# Reference solution: a fixed sequence of the task's skills, sent through the episode socket like an agent.
set -euo pipefail
ROBOUSE_REAL_ORACLE='[["move_joints", 30, -70, 60, -80, -90, 20]]' python -m robouse.oracle --backend real --env real-ros-joint-pose
