#!/bin/bash
# Reference solution: reads the target pose and calls the set_joint_targets skill, then hold. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend myosuite --env myosuite-hand-pose-9
