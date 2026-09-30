#!/bin/bash
# Reference solution: scripted drive_to / reach / grasp skills with waypoints through the doorways. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend mobile_manip --env tiago-bin-cans
