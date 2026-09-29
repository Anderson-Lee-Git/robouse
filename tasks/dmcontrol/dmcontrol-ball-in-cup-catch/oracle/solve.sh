#!/bin/bash
# Reference solution: sampling-based model-predictive control on a point-mass model of the cup, ball and string. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend dmcontrol --env dmcontrol-ball-in-cup-catch
