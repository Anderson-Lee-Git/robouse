#!/bin/bash
# Reference solution: scripted flight through the robo socket (drone.oracle_main).
set -euo pipefail
python -m robouse.oracle --backend drone --env drone-waypoint
