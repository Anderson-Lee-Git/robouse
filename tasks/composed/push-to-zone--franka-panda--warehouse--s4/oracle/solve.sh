#!/bin/bash
# Reference solution: the embodiment-agnostic push-to-zone strategy (components_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend components --env push-to-zone--franka-panda--warehouse--s4
