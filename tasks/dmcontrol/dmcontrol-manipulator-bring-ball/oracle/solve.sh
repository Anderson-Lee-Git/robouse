#!/bin/bash
# Reference solution: catches the rolling ball, grasps it from above and carries it (inverse kinematics, joint PID torques). It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend dmcontrol --env dmcontrol-manipulator-bring-ball
