#!/bin/bash
# Reference solution: scripted end-effector controller (maniskill_oracles.py) that drives the robot only
# through the robo socket and reads only the public observation.
set -euo pipefail
python -m robouse.oracle --backend maniskill --env maniskill-plug-charger
