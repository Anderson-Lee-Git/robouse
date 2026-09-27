#!/bin/bash
# Reference solution: scripted end-effector controller (robot0 grasps its end of the handle and brings the hammer to the middle, robot1 grasps the other end from above, robot0 releases and backs away) that drives the robot only through the robo socket
# and reads only the public observation fields.
set -euo pipefail
python -m robouse.oracle --backend robosuite --env TwoArmHandover
