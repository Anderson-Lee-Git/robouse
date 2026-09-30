#!/bin/bash
# Reference solution: the embodiment-agnostic go-to-landmark strategy (components_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend components --env go-to-landmark--google-robot--lab-bench--s5
