#!/bin/bash
# Reference solution: scripted with the walking skills and the public observation. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend humanoidbench --env humanoidbench-sit-simple
