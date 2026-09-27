#!/bin/bash
# Reference solution: scripted controller that uses only the robo socket (menagerie_sim/oracles.py).
set -euo pipefail
python -m robouse.oracle --backend menagerie --env menagerie-aloha-pawn-landing
