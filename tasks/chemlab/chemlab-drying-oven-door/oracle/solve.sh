#!/bin/bash
# Reference solution: Operate the forced-convection drying oven's door from the observed part positions. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend chemlab --env chemlab-drying-oven-door
