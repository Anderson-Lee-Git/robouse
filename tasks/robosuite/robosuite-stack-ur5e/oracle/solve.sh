#!/bin/bash
# Reference solution: scripted end-effector controller (pick the red cube, place it on the green cube, release, retreat) that drives the robot only through the robo socket
# and reads only the public observation fields.
set -euo pipefail
python -m robouse.oracle --backend robosuite --env Stack
