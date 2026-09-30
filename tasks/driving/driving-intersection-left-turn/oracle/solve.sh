#!/bin/bash
# Reference solution: scripted driving with the follow_route/change_lane/stop/wait skills and the public observation. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend driving --env driving-intersection-left-turn
