#!/bin/bash
# Reference solution: the embodiment-agnostic inspect-tag strategy (remix_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend remix --env inspect-tag--unitree-go2--tabletop--s1
