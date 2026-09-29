#!/bin/bash
# Reference solution: the embodiment-agnostic push-to-zone strategy (remix_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend remix --env push-to-zone--unitree-go2--workshop-bench--s4
