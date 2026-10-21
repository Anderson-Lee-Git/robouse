#!/bin/bash
# Reference solution: Operate the chemical fume hood's sash from the observed part positions. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend chemlab --env chemlab-fume-hood-sash
