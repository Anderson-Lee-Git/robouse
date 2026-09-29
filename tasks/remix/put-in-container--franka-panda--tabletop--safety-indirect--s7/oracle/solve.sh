#!/bin/bash
# Reference solution: the embodiment-agnostic put-in-container strategy (remix_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend remix --env put-in-container--franka-panda--tabletop--safety-indirect--s7
