#!/bin/bash
# Reference solution: scripted end-effector controller (grasp the lever from above, turn it along its arc until the latch releases, pull along the door's arc) that drives the robot only through the robo socket
# and reads only the public observation fields.
set -euo pipefail
python -m robouse.oracle --backend robosuite --env Door
