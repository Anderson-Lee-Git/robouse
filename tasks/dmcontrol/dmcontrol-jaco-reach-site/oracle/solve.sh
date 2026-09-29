#!/bin/bash
# Reference solution: scripted pick and place with the move_to and grip skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend dmcontrol --env dmcontrol-jaco-reach-site
