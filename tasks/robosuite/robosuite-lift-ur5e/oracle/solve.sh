#!/bin/bash
# Reference solution: scripted end-effector controller (grasp from above with the fingers across two faces, then lift) that drives the robot only through the robo socket
# and reads only the public observation fields.
set -euo pipefail
python -m robouse.oracle --backend robosuite --env Lift
