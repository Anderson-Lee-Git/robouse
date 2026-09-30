#!/bin/bash
# Reference solution: scripted waypoints with the walk_to / turn / look_at / sit / reach skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend quadruped --env spot-gauge-reading
