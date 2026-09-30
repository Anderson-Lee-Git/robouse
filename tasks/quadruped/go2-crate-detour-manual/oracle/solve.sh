#!/bin/bash
# Reference solution: a heading-controlled waypoint follower through robo act only. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend quadruped --env go2-crate-detour-manual
