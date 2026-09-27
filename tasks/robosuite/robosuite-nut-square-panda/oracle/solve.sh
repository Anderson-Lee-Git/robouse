#!/bin/bash
# Reference solution: scripted end-effector controller (grasp the handle, turn the nut so the handle faces the robot or sideways, servo the nut's centre over the peg, lower, release, retreat) that drives the robot only through the robo socket
# and reads only the public observation fields.
set -euo pipefail
python -m robouse.oracle --backend robosuite --env NutAssemblySquare
