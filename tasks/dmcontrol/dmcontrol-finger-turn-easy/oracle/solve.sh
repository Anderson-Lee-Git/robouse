#!/bin/bash
# Reference solution: pushes a spinner arm with the fingertip (inverse kinematics and joint PD torques). It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend dmcontrol --env dmcontrol-finger-turn-easy
