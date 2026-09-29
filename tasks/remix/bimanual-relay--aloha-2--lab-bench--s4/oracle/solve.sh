#!/bin/bash
# Reference solution: the embodiment-agnostic bimanual-relay strategy (remix_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend remix --env bimanual-relay--aloha-2--lab-bench--s4
