#!/bin/bash
# Reference solution: scripted end-effector controller (press the tool onto the table, then sweep to the nearest remaining marker, repeatedly) that drives the robot only through the robo socket
# and reads only the public observation fields.
set -euo pipefail
python -m robouse.oracle --backend robosuite --env Wipe
