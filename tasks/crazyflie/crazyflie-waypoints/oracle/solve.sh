#!/bin/bash
# Reference solution: scripted flight with the goto/land skills. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend crazyflie --env crazyflie-waypoints
