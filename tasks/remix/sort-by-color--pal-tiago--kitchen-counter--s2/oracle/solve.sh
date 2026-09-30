#!/bin/bash
# Reference solution: the embodiment-agnostic sort-by-color strategy (remix_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend remix --env sort-by-color--pal-tiago--kitchen-counter--s2
