#!/bin/bash
# Reference solution: scripted controller through the robo socket (act only on tasks without skills).
set -euo pipefail
python -m robouse.oracle --backend tabletop_hard --env hard-arc-img-rotate
