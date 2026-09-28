#!/bin/bash
# Reference solution: scripted reach / grasp skills using the public observation only. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend humanoid --env apollo-box-into-bin
