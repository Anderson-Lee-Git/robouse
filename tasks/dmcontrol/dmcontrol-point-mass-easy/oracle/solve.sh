#!/bin/bash
# Reference solution: PD force control to the target. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend dmcontrol --env dmcontrol-point-mass-easy
