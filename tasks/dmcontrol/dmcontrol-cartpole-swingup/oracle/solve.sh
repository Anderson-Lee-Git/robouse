#!/bin/bash
# Reference solution: energy-based swing-up and LQR balancing from the public state. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend dmcontrol --env dmcontrol-cartpole-swingup
