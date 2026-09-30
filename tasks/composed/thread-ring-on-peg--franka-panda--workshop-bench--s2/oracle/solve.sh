#!/bin/bash
# Reference solution: the embodiment-agnostic thread-ring-on-peg strategy (components_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend components --env thread-ring-on-peg--franka-panda--workshop-bench--s2
