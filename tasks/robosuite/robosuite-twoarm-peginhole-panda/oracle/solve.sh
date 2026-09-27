#!/bin/bash
# Reference solution: scripted end-effector controller (both arms turn about 45 degrees to a shared axis, then robot0 lines the peg up and pushes it through) that drives the robot only through the robo socket
# and reads only the public observation fields.
set -euo pipefail
python -m robouse.oracle --backend robosuite --env TwoArmPegInHole
