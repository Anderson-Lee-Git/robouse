#!/bin/bash
# Reference solution: reads the fingertip targets and calls the reach_tips skill, then hold. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend myosuite --env myosuite-finger-reach-random
