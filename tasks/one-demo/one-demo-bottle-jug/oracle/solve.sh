#!/bin/bash
# Reference solution: the family's strategy (onedemo.py), the one the demonstration ran, on this task's object,
# through the robo socket, reading only the public observation.
set -euo pipefail
python -m robouse.oracle --backend tabletop_onedemo --env one-demo-bottle-jug
