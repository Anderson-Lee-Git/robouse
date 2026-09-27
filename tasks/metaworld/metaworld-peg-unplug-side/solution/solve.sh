#!/bin/bash
# Reference solution: Meta-World's scripted expert, through the robo socket.
set -euo pipefail
python -m robouse.oracle --backend metaworld --env peg-unplug-side-v3 --steps 450
