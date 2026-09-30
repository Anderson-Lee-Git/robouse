#!/bin/bash
# Reference solution: sampling-based model-predictive control (cross-entropy method on the textbook acrobot model) and LQR at the top. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend dmcontrol --env dmcontrol-acrobot-swingup
