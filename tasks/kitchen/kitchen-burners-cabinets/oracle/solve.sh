#!/bin/bash
# Reference solution: scripted end-effector waypoints per subtask, through the robo socket only (public observations).
set -euo pipefail
python -m robouse.oracle --backend kitchen --env kitchen-burners-cabinets
