#!/bin/bash
# Reference solution: scripted end-effector controller (grasp the can from above, carry it over the target compartment at a safe height, lower, release, retreat) that drives the robot only through the robo socket
# and reads only the public observation fields.
set -euo pipefail
python -m robouse.oracle --backend robosuite --env PickPlaceCan
