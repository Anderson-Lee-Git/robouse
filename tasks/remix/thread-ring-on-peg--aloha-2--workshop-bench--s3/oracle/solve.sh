#!/bin/bash
# Reference solution: the embodiment-agnostic thread-ring-on-peg strategy (remix_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend remix --env thread-ring-on-peg--aloha-2--workshop-bench--s3
