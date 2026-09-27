#!/bin/bash
# Reference solution: scripted end-effector controller (both arms grasp their handles from above, then rise together) that drives the robot only through the robo socket
# and reads only the public observation fields.
set -euo pipefail
python -m robouse.oracle --backend robosuite --env TwoArmLift
