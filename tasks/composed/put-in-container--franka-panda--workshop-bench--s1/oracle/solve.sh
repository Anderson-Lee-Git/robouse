#!/bin/bash
# Reference solution: the embodiment-agnostic put-in-container strategy (components_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend components --env put-in-container--franka-panda--workshop-bench--s1
