#!/bin/bash
# Reference solution: the embodiment-agnostic fetch-and-deliver strategy (remix_sim/strategies.py) with the declared skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend remix --env fetch-and-deliver--google-robot--workshop-bench--s3
