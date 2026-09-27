#!/bin/bash
# Reference solution: Meta-World's scripted expert, through the robo socket.
set -euo pipefail
python -m robouse.oracle --backend metaworld --env stick-pull-v3 --steps 450
