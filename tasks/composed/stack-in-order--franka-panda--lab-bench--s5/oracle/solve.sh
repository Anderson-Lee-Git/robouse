#!/bin/bash
# Reference solution: the embodiment-agnostic stack-in-order strategy (components_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend components --env stack-in-order--franka-panda--lab-bench--s5
