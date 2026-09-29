#!/bin/bash
# Reference solution: the embodiment-agnostic inspect-tag strategy (remix_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend remix --env inspect-tag--google-robot--kitchen-counter--s4
