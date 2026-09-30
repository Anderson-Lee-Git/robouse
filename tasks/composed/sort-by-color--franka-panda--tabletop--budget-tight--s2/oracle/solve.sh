#!/bin/bash
# Reference solution: the embodiment-agnostic sort-by-color strategy (components_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend components --env sort-by-color--franka-panda--tabletop--budget-tight--s2
