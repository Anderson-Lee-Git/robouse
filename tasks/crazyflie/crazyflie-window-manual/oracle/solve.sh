#!/bin/bash
# Reference solution: a proportional controller on the drone's predicted stopping point, through robo act only. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend crazyflie --env crazyflie-window-manual
