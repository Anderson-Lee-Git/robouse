#!/bin/bash
# Reference solution: the embodiment-agnostic stack-in-order strategy (remix_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend remix --env stack-in-order--aloha-2--tabletop--s4
